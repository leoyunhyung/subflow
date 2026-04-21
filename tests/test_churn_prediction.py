"""
churn_prediction 앱 테스트.

포인트:
    1) 실제 Claude API 는 호출하지 않는다. ClaudeGateway 는 mock.
    2) feature_extractor 는 실 ORM 로 검증 (피처 계산이 제일 많은 버그 포인트).
    3) Gateway 의 스키마 검증 / 재시도 / 4xx-5xx 분기를 별도로 검증.
    4) 배치 task 의 정합성 검증 로직까지 검증.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.churn_prediction.models import (
    ChurnPrediction,
    ChurnPredictionRun,
    ChurnRiskLevel,
)
from apps.churn_prediction.services import llm_gateway
from apps.churn_prediction.services.feature_extractor import extract_features
from apps.churn_prediction.services.llm_gateway import (
    ClaudeGateway,
    LLMResponseError,
    _extract_json_block,
    _validate_prediction_schema,
)
from apps.churn_prediction.services.predictor import predict_for_subscription
from apps.churn_prediction.tasks import (
    predict_churn_batch,
    predict_churn_for_subscription,
)
from apps.payments.models import Payment
from apps.plans.models import Plan
from apps.subscriptions.models import Subscription


# ---------------------------------------------------------------------------
# fixtures (conftest.py 의 vendor/admin_user 등 재사용)
# ---------------------------------------------------------------------------
@pytest.fixture
def plan(vendor):
    return Plan.objects.create(
        vendor=vendor,
        name="Pro",
        tier=Plan.Tier.PRO,
        billing_cycle=Plan.BillingCycle.MONTHLY,
        price=29000,
    )


@pytest.fixture
def active_subscription(normal_user, plan):
    return Subscription.objects.create(
        user=normal_user,
        plan=plan,
        expires_at=timezone.now() + timedelta(days=20),
    )


@pytest.fixture
def at_risk_subscription(normal_user, plan):
    """결제 실패 이력이 있는 위험 구독."""
    sub = Subscription.objects.create(
        user=normal_user,
        plan=plan,
        expires_at=timezone.now() + timedelta(days=5),  # 만료 임박
    )
    # 최근 결제 실패 2건
    Payment.objects.create(
        user=normal_user,
        subscription=sub,
        amount=29000,
        status=Payment.Status.FAILED,
    )
    Payment.objects.create(
        user=normal_user,
        subscription=sub,
        amount=29000,
        status=Payment.Status.FAILED,
    )
    return sub


def _mock_claude_success(risk_score=82, risk_level="critical"):
    """Gateway.predict_churn 의 성공 응답을 흉내내는 dict."""
    return {
        "success": True,
        "data": {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "reasoning": "만료 임박 + 결제 실패 2건",
            "recommended_actions": ["할인 쿠폰 발송", "고객 성공 담당 연락"],
            "_meta": {
                "model": "claude-opus-4-5",
                "input_tokens": 300,
                "output_tokens": 120,
                "latency_ms": 1234,
                "raw_response": {"id": "msg_test"},
            },
        },
    }


# ---------------------------------------------------------------------------
# 1) 응답 파서 / 스키마 검증
# ---------------------------------------------------------------------------
class TestResponseParser:
    def test_extract_json_from_markdown_block(self):
        text = '```json\n{"risk_score": 50, "risk_level": "medium"}\n```'
        assert _extract_json_block(text)["risk_score"] == 50

    def test_extract_json_from_naked_json(self):
        text = '설명입니다. {"risk_score": 10, "risk_level": "low"} 끝.'
        assert _extract_json_block(text)["risk_level"] == "low"

    def test_extract_json_no_json_raises(self):
        with pytest.raises(LLMResponseError):
            _extract_json_block("JSON 없음")

    def test_validate_schema_ok(self):
        _validate_prediction_schema(
            {
                "risk_score": 30,
                "risk_level": "medium",
                "reasoning": "x",
                "recommended_actions": [],
            }
        )

    @pytest.mark.parametrize(
        "payload,expected_msg",
        [
            ({"risk_level": "low", "reasoning": "x", "recommended_actions": []}, "필수 필드 누락"),
            (
                {
                    "risk_score": 150,
                    "risk_level": "low",
                    "reasoning": "x",
                    "recommended_actions": [],
                },
                "risk_score 범위",
            ),
            (
                {
                    "risk_score": 50,
                    "risk_level": "urgent",
                    "reasoning": "x",
                    "recommended_actions": [],
                },
                "risk_level 값",
            ),
            (
                {
                    "risk_score": 50,
                    "risk_level": "low",
                    "reasoning": "x",
                    "recommended_actions": "not a list",
                },
                "리스트",
            ),
        ],
    )
    def test_validate_schema_errors(self, payload, expected_msg):
        with pytest.raises(LLMResponseError) as exc:
            _validate_prediction_schema(payload)
        assert expected_msg in str(exc.value)


# ---------------------------------------------------------------------------
# 2) Feature Extractor
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestFeatureExtractor:
    def test_healthy_subscription_not_candidate(self, active_subscription):
        result = extract_features(active_subscription)
        assert result.is_candidate is False
        assert result.skip_reason == "healthy"
        assert result.data["payment_fail_count_90d"] == 0

    def test_payment_fail_triggers_candidate(self, at_risk_subscription):
        result = extract_features(at_risk_subscription)
        assert result.is_candidate is True
        assert result.data["payment_fail_count_90d"] == 2

    def test_expiry_imminent_triggers_candidate(self, active_subscription):
        active_subscription.expires_at = timezone.now() + timedelta(days=3)
        active_subscription.save()
        result = extract_features(active_subscription)
        assert result.is_candidate is True

    def test_cancelled_subscription_skipped(self, active_subscription):
        active_subscription.status = Subscription.Status.CANCELLED
        active_subscription.save()
        result = extract_features(active_subscription)
        assert result.is_candidate is False
        assert "cancelled" in result.skip_reason

    def test_features_contain_plan_metadata(self, at_risk_subscription):
        result = extract_features(at_risk_subscription)
        assert result.data["plan_tier"] == "pro"
        assert result.data["billing_cycle"] == "monthly"
        assert result.data["plan_price"] == 29000


# ---------------------------------------------------------------------------
# 3) Predictor (orchestration)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPredictor:
    def test_skipped_when_healthy(self, active_subscription):
        gateway = ClaudeGateway(api_key="dummy")
        with patch.object(gateway, "predict_churn") as mock_pred:
            result = predict_for_subscription(active_subscription, gateway=gateway)
        assert result.skipped is True
        mock_pred.assert_not_called()

    def test_force_true_calls_llm_even_if_healthy(self, active_subscription):
        gateway = ClaudeGateway(api_key="dummy")
        with patch.object(
            gateway, "predict_churn", return_value=_mock_claude_success(20, "low")
        ) as mock_pred:
            result = predict_for_subscription(
                active_subscription, gateway=gateway, force=True
            )
        assert result.ok
        mock_pred.assert_called_once()
        assert result.prediction.risk_score == 20
        assert result.prediction.risk_level == ChurnRiskLevel.LOW

    def test_success_saves_prediction_and_snapshot(self, at_risk_subscription):
        gateway = ClaudeGateway(api_key="dummy")
        with patch.object(
            gateway, "predict_churn", return_value=_mock_claude_success()
        ):
            result = predict_for_subscription(
                at_risk_subscription, gateway=gateway
            )
        assert result.ok
        pred = result.prediction
        assert pred.risk_score == 82
        assert pred.risk_level == "critical"
        assert pred.feature_snapshot.feature_data["payment_fail_count_90d"] == 2
        assert pred.llm_provider == "claude"

    def test_rerun_same_day_replaces_prediction(self, at_risk_subscription):
        gateway = ClaudeGateway(api_key="dummy")
        with patch.object(
            gateway, "predict_churn", return_value=_mock_claude_success(50, "high")
        ):
            predict_for_subscription(at_risk_subscription, gateway=gateway)
        with patch.object(
            gateway, "predict_churn", return_value=_mock_claude_success(90, "critical")
        ):
            predict_for_subscription(at_risk_subscription, gateway=gateway)

        preds = ChurnPrediction.objects.filter(subscription=at_risk_subscription)
        assert preds.count() == 1
        assert preds.first().risk_score == 90

    def test_gateway_error_returns_failure(self, at_risk_subscription):
        gateway = ClaudeGateway(api_key="dummy")
        err_resp = {
            "success": False,
            "error": {"code": "HTTP_500", "message": "upstream"},
        }
        with patch.object(gateway, "predict_churn", return_value=err_resp):
            result = predict_for_subscription(
                at_risk_subscription, gateway=gateway
            )
        assert not result.ok
        assert "HTTP_500" in result.error
        assert ChurnPrediction.objects.count() == 0


# ---------------------------------------------------------------------------
# 4) Tasks (batch + single)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBatchTask:
    def test_batch_creates_run_with_integrity_check(
        self, active_subscription, at_risk_subscription, admin_user
    ):
        # mock 은 gateway 레벨이 아니라 predictor 내부가 쓰는 get_llm_gateway 레벨에서
        fake_gw = ClaudeGateway(api_key="dummy")
        with patch.object(
            fake_gw, "predict_churn", return_value=_mock_claude_success()
        ), patch(
            "apps.churn_prediction.services.predictor.get_llm_gateway",
            return_value=fake_gw,
        ):
            predict_churn_batch(executed_by_id=admin_user.id)

        run = ChurnPredictionRun.objects.latest("created_at")
        assert run.expected_count == 2
        # 1건은 healthy 로 스킵, 1건은 실제 예측
        assert run.actual_count == 1
        assert run.skipped_count == 1
        assert run.failed_count == 0
        assert run.is_verified is True
        assert run.status == ChurnPredictionRun.Status.SUCCESS
        assert run.total_input_tokens == 300
        assert run.total_output_tokens == 120
        assert run.estimated_cost_usd > 0

    def test_batch_no_active_subscriptions(self, admin_user):
        predict_churn_batch(executed_by_id=admin_user.id)
        run = ChurnPredictionRun.objects.latest("created_at")
        assert run.expected_count == 0
        assert run.status == ChurnPredictionRun.Status.SUCCESS
        assert run.is_verified is True

    def test_single_task_success(self, at_risk_subscription, admin_user):
        fake_gw = ClaudeGateway(api_key="dummy")
        with patch.object(
            fake_gw, "predict_churn", return_value=_mock_claude_success()
        ), patch(
            "apps.churn_prediction.services.predictor.get_llm_gateway",
            return_value=fake_gw,
        ):
            result = predict_churn_for_subscription(
                subscription_id=at_risk_subscription.id,
                executed_by_id=admin_user.id,
            )
        assert result["ok"] is True
        run = ChurnPredictionRun.objects.latest("created_at")
        assert run.trigger_type == ChurnPredictionRun.TriggerType.MANUAL
        assert run.executed_by_id == admin_user.id
        assert run.actual_count == 1

    def test_single_task_subscription_not_found(self, admin_user):
        result = predict_churn_for_subscription(
            subscription_id=99999, executed_by_id=admin_user.id
        )
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 5) View — admin 권한 / 동기 엔드포인트
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestViews:
    def test_list_requires_admin(self, user_client):
        res = user_client.get("/api/v1/churn/predictions/")
        assert res.status_code == 403

    def test_predict_sync_success(self, admin_client, at_risk_subscription):
        fake_gw = ClaudeGateway(api_key="dummy")
        with patch.object(
            fake_gw, "predict_churn", return_value=_mock_claude_success()
        ), patch(
            "apps.churn_prediction.services.predictor.get_llm_gateway",
            return_value=fake_gw,
        ):
            res = admin_client.post(
                "/api/v1/churn/predictions/predict-sync/",
                {"subscription_id": at_risk_subscription.id},
                format="json",
            )
        assert res.status_code == 200
        assert res.data["risk_score"] == 82

    def test_predict_sync_missing_id(self, admin_client):
        res = admin_client.post(
            "/api/v1/churn/predictions/predict-sync/", {}, format="json"
        )
        assert res.status_code == 400

    def test_predict_sync_subscription_not_found(self, admin_client):
        res = admin_client.post(
            "/api/v1/churn/predictions/predict-sync/",
            {"subscription_id": 99999},
            format="json",
        )
        assert res.status_code == 404

    def test_predict_async_queues_task(self, admin_client, at_risk_subscription):
        # CELERY_TASK_ALWAYS_EAGER 라 실제 실행되지만 gateway 를 mock 해야 함
        fake_gw = ClaudeGateway(api_key="dummy")
        with patch.object(
            fake_gw, "predict_churn", return_value=_mock_claude_success()
        ), patch(
            "apps.churn_prediction.services.predictor.get_llm_gateway",
            return_value=fake_gw,
        ):
            res = admin_client.post(
                "/api/v1/churn/predictions/predict/",
                {"subscription_id": at_risk_subscription.id},
                format="json",
            )
        assert res.status_code == 202
        assert "task_id" in res.data

    def test_runs_list(self, admin_client):
        ChurnPredictionRun.objects.create(
            prediction_date=timezone.localdate(),
            status=ChurnPredictionRun.Status.SUCCESS,
            expected_count=5,
            actual_count=2,
            skipped_count=3,
            is_verified=True,
        )
        res = admin_client.get("/api/v1/churn/runs/")
        assert res.status_code == 200
        assert res.data["count"] == 1
        assert res.data["results"][0]["integrity_message"] == "정상 처리 완료"
