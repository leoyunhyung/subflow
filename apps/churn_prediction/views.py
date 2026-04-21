"""
이탈 예측 API.

엔드포인트 (admin 또는 vendor 권한 전제):
    GET    /api/v1/churn/predictions/                  : 예측 결과 목록 (필터: risk_level, date)
    GET    /api/v1/churn/predictions/{id}/             : 예측 결과 단건
    POST   /api/v1/churn/predictions/predict/          : 특정 구독 즉시 재예측 (비동기 큐잉)
    POST   /api/v1/churn/predictions/predict-sync/     : 특정 구독 즉시 재예측 (동기)
    GET    /api/v1/churn/runs/                         : 배치 실행 이력

면접 대비:
    - 동기 / 비동기 엔드포인트 둘 다 제공하는 이유를 명확히 분리.
    - 동기는 Admin 단일 유저 조회용 (2-5초 대기 가능).
    - 비동기는 수만 건 배치 / 프론트에서 로딩 UX 를 주는 경우용.
"""
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.churn_prediction.models import ChurnPrediction, ChurnPredictionRun
from apps.churn_prediction.serializers import (
    ChurnPredictionRunSerializer,
    ChurnPredictionSerializer,
)
from apps.churn_prediction.services.predictor import predict_for_subscription
from apps.churn_prediction.tasks import predict_churn_for_subscription
from apps.common.permissions import IsAdmin


class ChurnPredictionViewSet(ReadOnlyModelViewSet):
    queryset = (
        ChurnPrediction.objects.select_related(
            "subscription__plan__vendor",
            "subscription__user",
            "feature_snapshot",
        )
        .all()
    )
    serializer_class = ChurnPredictionSerializer
    permission_classes = [IsAdmin]
    filterset_fields = ["risk_level", "prediction_date", "subscription"]
    ordering_fields = ["prediction_date", "risk_score", "created_at"]
    ordering = ["-prediction_date", "-risk_score"]

    @extend_schema(
        summary="특정 구독 즉시 재예측 (비동기)",
        description="Celery 태스크로 큐잉. 결과는 GET /api/v1/churn/predictions/ 로 조회.",
        request={
            "application/json": {
                "type": "object",
                "properties": {"subscription_id": {"type": "integer"}},
                "required": ["subscription_id"],
            }
        },
        responses={202: {"type": "object"}},
    )
    @action(detail=False, methods=["post"], url_path="predict")
    def predict_async(self, request):
        sub_id = request.data.get("subscription_id")
        if not sub_id:
            return Response(
                {"error": "subscription_id 필수"}, status=status.HTTP_400_BAD_REQUEST
            )
        task = predict_churn_for_subscription.delay(
            subscription_id=sub_id, executed_by_id=request.user.id
        )
        return Response(
            {"task_id": task.id, "subscription_id": sub_id},
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        summary="특정 구독 즉시 재예측 (동기)",
        description=(
            "LLM 호출 완료까지 대기 후 결과 반환. 2-5초 소요 가능.\n"
            "관리자가 단일 유저를 바로 확인할 때 사용."
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {"subscription_id": {"type": "integer"}},
                "required": ["subscription_id"],
            }
        },
        responses={200: ChurnPredictionSerializer},
    )
    @action(detail=False, methods=["post"], url_path="predict-sync")
    def predict_sync(self, request):
        from apps.subscriptions.models import Subscription

        sub_id = request.data.get("subscription_id")
        if not sub_id:
            return Response(
                {"error": "subscription_id 필수"}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            subscription = Subscription.objects.select_related("plan", "user").get(
                pk=sub_id
            )
        except Subscription.DoesNotExist:
            return Response(
                {"error": "subscription not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = predict_for_subscription(subscription, force=True)
        if not result.ok:
            return Response(
                {"error": result.error or "prediction failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            ChurnPredictionSerializer(result.prediction).data,
            status=status.HTTP_200_OK,
        )


class ChurnPredictionRunViewSet(ReadOnlyModelViewSet):
    queryset = ChurnPredictionRun.objects.all().select_related("executed_by")
    serializer_class = ChurnPredictionRunSerializer
    permission_classes = [IsAdmin]
    filterset_fields = ["status", "trigger_type", "prediction_date"]
    ordering_fields = ["created_at", "prediction_date"]
    ordering = ["-created_at"]
