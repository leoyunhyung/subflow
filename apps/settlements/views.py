from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdmin, IsVendor

from .models import Settlement, SettlementHistory, SettlementRate
from .serializers import (
    SettlementHistorySerializer,
    SettlementRateSerializer,
    SettlementSerializer,
)
from .tasks import generate_settlements


class SettlementListView(generics.ListAPIView):
    """정산 목록 조회 (Admin: 전체, Vendor: 본인)"""

    serializer_class = SettlementSerializer

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = Settlement.objects.select_related("vendor", "settlement_rate").prefetch_related(
            "user_settlements__user"
        )
        if user.role == "vendor":
            return qs.filter(vendor__user=user)
        if user.role == "admin":
            return qs.all()
        return qs.none()


class SettlementCompleteView(APIView):
    """정산 완료 처리 (Admin)"""

    permission_classes = (permissions.IsAuthenticated, IsAdmin)

    def post(self, request, pk):
        try:
            settlement = Settlement.objects.get(pk=pk, status="pending")
        except Settlement.DoesNotExist:
            return Response(
                {"detail": "대기 중인 정산을 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND
            )
        settlement.mark_completed()
        return Response(SettlementSerializer(settlement).data)


class SettlementGenerateView(APIView):
    """정산 데이터 생성 트리거 (Admin) - Celery 비동기"""

    permission_classes = (permissions.IsAuthenticated, IsAdmin)

    def post(self, request):
        period_start = request.data.get("period_start")
        period_end = request.data.get("period_end")
        if not period_start or not period_end:
            return Response(
                {"detail": "period_start, period_end 필수입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        generate_settlements.delay(period_start, period_end, user_id=request.user.pk)
        return Response(
            {"detail": "정산 생성 작업이 시작되었습니다."}, status=status.HTTP_202_ACCEPTED
        )


class SettlementHistoryListView(generics.ListAPIView):
    """정산 실행 이력 조회 (Admin)"""

    serializer_class = SettlementHistorySerializer
    permission_classes = (permissions.IsAuthenticated, IsAdmin)
    queryset = SettlementHistory.objects.select_related("executed_by").all()


class SettlementRateListCreateView(generics.ListCreateAPIView):
    """정산율 조회/등록 (Admin)"""

    serializer_class = SettlementRateSerializer
    permission_classes = (permissions.IsAuthenticated, IsAdmin)
    queryset = SettlementRate.objects.select_related("vendor").all()
