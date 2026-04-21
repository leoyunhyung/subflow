"""
예측 오케스트레이션.

단일 구독에 대해:
    1) 피처 추출
    2) (선택) 위험군 후보 필터 — 비용 제어
    3) LLM Gateway 호출
    4) 응답 저장 (FeatureSnapshot + Prediction)

이 레이어는 "한 건" 처리만 책임진다. 다수 구독 배치는 tasks.py 가 담당.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.churn_prediction.models import (
    ChurnFeatureSnapshot,
    ChurnPrediction,
)
from apps.churn_prediction.services.feature_extractor import (
    FEATURE_VERSION,
    extract_features,
)
from apps.churn_prediction.services.llm_gateway import (
    BaseLLMGateway,
    get_llm_gateway,
)

logger = logging.getLogger(__name__)

# Anthropic Claude Opus 4 대략 단가 (2025 기준, 1M 토큰당 USD)
# 실제 운영에서는 config/환경변수로 관리. 여기선 예상 비용 표기용.
COST_PER_MTOK_INPUT = Decimal("15")
COST_PER_MTOK_OUTPUT = Decimal("75")


class PredictionResult:
    """save_prediction 의 반환값 컨테이너."""

    def __init__(
        self,
        prediction: ChurnPrediction | None = None,
        skipped: bool = False,
        skip_reason: str = "",
        error: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        self.prediction = prediction
        self.skipped = skipped
        self.skip_reason = skip_reason
        self.error = error
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    @property
    def ok(self) -> bool:
        return self.prediction is not None and not self.error


def estimate_cost(input_tokens: int, output_tokens: int) -> Decimal:
    return (
        Decimal(input_tokens) * COST_PER_MTOK_INPUT / Decimal(1_000_000)
        + Decimal(output_tokens) * COST_PER_MTOK_OUTPUT / Decimal(1_000_000)
    ).quantize(Decimal("0.0001"))


def predict_for_subscription(
    subscription,
    *,
    gateway: BaseLLMGateway | None = None,
    force: bool = False,
    prompt_version: str = "v1",
) -> PredictionResult:
    """
    한 구독 건에 대한 이탈 예측 수행 + 저장.

    Args:
        subscription: Subscription 인스턴스
        gateway: 테스트에서 mock 주입 가능. 없으면 factory 로 생성.
        force: True 면 위험군 필터를 무시하고 무조건 LLM 호출.
               (관리자가 수동으로 "다시 계산" 눌렀을 때 사용)
        prompt_version: 저장 시 기록할 프롬프트 버전

    Returns:
        PredictionResult
    """
    gateway = gateway or get_llm_gateway()
    today = timezone.localdate()

    extracted = extract_features(subscription)

    # 비용 제어: 위험군 후보가 아니면 LLM 호출 생략
    if not force and not extracted.is_candidate:
        logger.debug(
            "sub#%s LLM 호출 스킵 (%s)",
            subscription.pk,
            extracted.skip_reason,
        )
        return PredictionResult(skipped=True, skip_reason=extracted.skip_reason)

    result = gateway.predict_churn(extracted.data, prompt_version=prompt_version)
    if not result["success"]:
        err = result["error"]
        logger.error(
            "sub#%s LLM 호출 실패: %s %s",
            subscription.pk,
            err.get("code"),
            err.get("message"),
        )
        return PredictionResult(
            error=f'{err.get("code")}: {err.get("message")}'
        )

    data = result["data"]
    meta = data["_meta"]

    # --- 저장 ---
    # 같은 구독 + 같은 날짜 기존 예측은 삭제 후 재생성 (force 재실행 지원)
    with transaction.atomic():
        ChurnPrediction.objects.filter(
            subscription=subscription, prediction_date=today
        ).delete()

        snapshot = ChurnFeatureSnapshot.objects.create(
            subscription=subscription,
            feature_data=extracted.data,
            feature_version=FEATURE_VERSION,
        )

        prediction = ChurnPrediction.objects.create(
            subscription=subscription,
            feature_snapshot=snapshot,
            prediction_date=today,
            risk_score=data["risk_score"],
            risk_level=data["risk_level"],
            reasoning=data["reasoning"],
            recommended_actions=data["recommended_actions"],
            llm_provider=gateway.provider_name,
            llm_model=meta["model"],
            prompt_version=prompt_version,
            input_tokens=meta["input_tokens"],
            output_tokens=meta["output_tokens"],
            latency_ms=meta["latency_ms"],
            raw_response=meta["raw_response"],
        )

    return PredictionResult(
        prediction=prediction,
        input_tokens=meta["input_tokens"],
        output_tokens=meta["output_tokens"],
    )
