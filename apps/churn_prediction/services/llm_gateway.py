"""
LLM Gateway.

설계 의도:
    - 결제(TossPayments) 연동에서 쓴 Gateway 패턴을 LLM 에도 동일하게 적용.
    - "PG 교체 가능성 대비" 와 같은 논리로 "LLM 제공자 교체 가능성 대비".
    - 재시도 / 타임아웃 / 4xx-5xx 분기를 TossPaymentsService 와 동일 규약으로 구현.

구조:
    BaseLLMGateway  -- 인터페이스 정의 (predict_churn)
      └── ClaudeGateway  -- Anthropic Messages API 구현
      └── (추후) OpenAIGateway / GeminiGateway 등 추가 가능

반환 규약:
    {
        "success": bool,
        "data": {
            "risk_score": int,           # 0-100
            "risk_level": str,           # low / medium / high / critical
            "reasoning": str,
            "recommended_actions": list[str],
            "_meta": {
                "model": str,
                "input_tokens": int,
                "output_tokens": int,
                "latency_ms": int,
                "raw_response": dict,
            },
        },
        "error": {"code": str, "message": str}  # success=False 일 때만
    }
"""
from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 응답 파싱 / 검증 헬퍼
# ---------------------------------------------------------------------------
_REQUIRED_FIELDS = ("risk_score", "risk_level", "reasoning", "recommended_actions")
_ALLOWED_LEVELS = {"low", "medium", "high", "critical"}


class LLMResponseError(Exception):
    """LLM 응답이 예상한 스키마를 따르지 않을 때."""


def _extract_json_block(text: str) -> dict:
    """
    LLM 응답 텍스트에서 JSON 오브젝트만 뽑아낸다.

    LLM 이 가끔 ```json ... ``` 로 감싸거나 앞뒤에 해설을 붙이므로
    가장 바깥쪽 { ... } 를 greedy 로 매칭해서 파싱.
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise LLMResponseError(f"응답에 JSON 오브젝트가 없음: {text[:200]}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise LLMResponseError(f"JSON 파싱 실패: {e} / raw={text[:200]}") from e


def _validate_prediction_schema(payload: dict) -> None:
    """
    필수 필드 존재 + 값 범위 검증.
    settlements 의 "정합성 검증" 사상과 동일 — 저장 전 사전 차단.
    """
    missing = [f for f in _REQUIRED_FIELDS if f not in payload]
    if missing:
        raise LLMResponseError(f"필수 필드 누락: {missing}")

    score = payload["risk_score"]
    if not isinstance(score, int) or not 0 <= score <= 100:
        raise LLMResponseError(f"risk_score 범위 위반: {score}")

    level = payload["risk_level"]
    if level not in _ALLOWED_LEVELS:
        raise LLMResponseError(f"risk_level 값 위반: {level}")

    if not isinstance(payload["recommended_actions"], list):
        raise LLMResponseError("recommended_actions 는 리스트여야 함")


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
class BaseLLMGateway(ABC):
    """LLM 제공자 교체를 위한 공통 인터페이스."""

    provider_name: str = "base"
    max_retries: int = 3
    retry_delay: float = 1.0
    timeout: int = 30

    @abstractmethod
    def predict_churn(self, features: dict, prompt_version: str = "v1") -> dict:
        """피처 JSON 을 입력받아 이탈 예측 결과를 반환. 반환 규약은 모듈 docstring 참조."""


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_API_VERSION = "2023-06-01"


CHURN_SYSTEM_PROMPT_V1 = """\
당신은 SaaS 구독 서비스의 데이터 분석가다. 주어진 구독 피처를 근거로
이탈 가능성을 판단하고, 아래 JSON 스키마에 정확히 맞춰 응답해야 한다.

반드시 JSON 오브젝트 **하나만** 출력해라. 해설, 마크다운, 코드블록 금지.

스키마:
{
  "risk_score": 0-100 사이 정수,
  "risk_level": "low" | "medium" | "high" | "critical",
  "reasoning": "판단 근거 2-3문장 (한국어)",
  "recommended_actions": ["리텐션 액션 1", "리텐션 액션 2", ...]
}

판단 기준:
- 최근 결제 실패가 누적되면 위험도 상승
- 만료일이 임박했는데 연장 결제 이력이 없으면 위험도 상승
- 해지 시도 이력이 있으면 위험도 상승
- 구독 가입 후 경과 기간이 짧은데 결제 실패가 있으면 매우 위험
- 장기 구독자(180일+)인데 최근 결제 실패 1건 정도는 위험도 낮음

risk_level 매핑:
- 0-24: low
- 25-49: medium
- 50-74: high
- 75-100: critical
"""


class ClaudeGateway(BaseLLMGateway):
    provider_name = "claude"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
    ):
        self.api_key = api_key or getattr(settings, "ANTHROPIC_API_KEY", "")
        self.model = model or getattr(
            settings, "CHURN_LLM_MODEL", "claude-opus-4-5"
        )
        self.max_tokens = max_tokens

    # ---- HTTP ----
    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": CLAUDE_API_VERSION,
            "content-type": "application/json",
        }

    def _request_with_retry(self, payload: dict) -> requests.Response | None:
        """TossPaymentsService._request_with_retry 와 동일 규약."""
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    CLAUDE_API_URL,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout,
                )
            except requests.exceptions.Timeout:
                logger.warning(
                    "Claude timeout (attempt %d/%d)", attempt, self.max_retries
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)
                continue
            except requests.exceptions.ConnectionError:
                logger.warning(
                    "Claude connection error (attempt %d/%d)",
                    attempt,
                    self.max_retries,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)
                continue

            # 4xx 는 재시도 안 함 (잘못된 요청 / 인증 실패)
            if 400 <= response.status_code < 500:
                return response

            # 5xx / 429 는 재시도
            if response.status_code >= 500 or response.status_code == 429:
                logger.warning(
                    "Claude %d (attempt %d/%d)",
                    response.status_code,
                    attempt,
                    self.max_retries,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)
                    continue

            return response

        return None

    # ---- 퍼블릭 ----
    def predict_churn(self, features: dict, prompt_version: str = "v1") -> dict:
        if not self.api_key:
            return {
                "success": False,
                "error": {
                    "code": "CONFIG_ERROR",
                    "message": "ANTHROPIC_API_KEY 미설정",
                },
            }

        user_content = (
            "다음은 한 구독 건의 피처 데이터다. 이탈 가능성을 판단해라.\n\n"
            f"```json\n{json.dumps(features, ensure_ascii=False, indent=2)}\n```"
        )

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": CHURN_SYSTEM_PROMPT_V1,
            "messages": [{"role": "user", "content": user_content}],
        }

        start = time.monotonic()
        response = self._request_with_retry(payload)
        latency_ms = int((time.monotonic() - start) * 1000)

        if response is None:
            return {
                "success": False,
                "error": {
                    "code": "NETWORK_ERROR",
                    "message": f"Claude API 재시도 {self.max_retries}회 실패",
                },
            }

        if response.status_code != 200:
            try:
                err_body = response.json()
            except ValueError:
                err_body = {"raw": response.text[:300]}
            logger.error("Claude API %d: %s", response.status_code, err_body)
            return {
                "success": False,
                "error": {
                    "code": f"HTTP_{response.status_code}",
                    "message": str(err_body),
                },
            }

        raw = response.json()
        try:
            text = raw["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as e:
            return {
                "success": False,
                "error": {
                    "code": "UNEXPECTED_RESPONSE",
                    "message": f"응답 구조 이상: {e} / raw={str(raw)[:200]}",
                },
            }

        try:
            parsed = _extract_json_block(text)
            _validate_prediction_schema(parsed)
        except LLMResponseError as e:
            return {
                "success": False,
                "error": {"code": "SCHEMA_ERROR", "message": str(e)},
            }

        usage = raw.get("usage", {}) or {}
        parsed["_meta"] = {
            "model": raw.get("model", self.model),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "latency_ms": latency_ms,
            "raw_response": raw,
        }
        return {"success": True, "data": parsed}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_llm_gateway() -> BaseLLMGateway:
    """
    settings.CHURN_LLM_PROVIDER 에 따라 Gateway 인스턴스 반환.
    기본값은 claude.
    """
    provider = getattr(settings, "CHURN_LLM_PROVIDER", "claude").lower()
    if provider == "claude":
        return ClaudeGateway()
    raise ValueError(f"지원하지 않는 LLM 제공자: {provider}")
