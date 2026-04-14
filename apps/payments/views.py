from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsUser

from .models import Payment
from .serializers import PaymentConfirmSerializer, PaymentSerializer
from .services import TossPaymentsService


class PaymentCreateView(generics.CreateAPIView):
    """결제 요청 생성 (User)"""

    serializer_class = PaymentSerializer
    permission_classes = (permissions.IsAuthenticated, IsUser)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PaymentConfirmView(APIView):
    """토스페이먼츠 결제 승인 콜백"""

    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        serializer = PaymentConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            payment = Payment.objects.get(
                order_id=data["order_id"],
                user=request.user,
                status="pending",
            )
        except Payment.DoesNotExist:
            return Response(
                {"detail": "결제 정보를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND
            )

        if payment.amount != data["amount"]:
            return Response(
                {"detail": "결제 금액이 일치하지 않습니다."}, status=status.HTTP_400_BAD_REQUEST
            )

        result = TossPaymentsService.confirm_payment(
            payment_key=data["payment_key"],
            order_id=str(payment.order_id),
            amount=payment.amount,
        )

        if result["success"]:
            payment.status = "done"
            payment.toss_payment_key = data["payment_key"]
            payment.paid_at = timezone.now()
            payment.save(update_fields=["status", "toss_payment_key", "paid_at"])
            return Response(PaymentSerializer(payment).data)

        payment.status = "failed"
        payment.save(update_fields=["status"])
        return Response(
            {"detail": "결제 승인 실패", "error": result["error"]},
            status=status.HTTP_400_BAD_REQUEST,
        )


class PaymentWebhookView(APIView):
    """
    토스페이먼츠 Webhook 수신 엔드포인트

    PG사가 결제 상태 변경 시 서버에 직접 통보하는 콜백.
    - DONE: 결제 완료
    - CANCELED: 결제 취소
    - FAILED: 결제 실패
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        event_type = request.data.get("eventType")
        data = request.data.get("data", {})
        order_id = data.get("orderId")
        payment_key = data.get("paymentKey")
        status_value = data.get("status")

        if not order_id:
            return Response({"detail": "orderId is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payment = Payment.objects.get(order_id=order_id)
        except Payment.DoesNotExist:
            return Response(
                {"detail": "결제 정보를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND
            )

        if status_value == "DONE" and payment.status == "pending":
            payment.status = "done"
            payment.toss_payment_key = payment_key or ""
            payment.paid_at = timezone.now()
            payment.save(update_fields=["status", "toss_payment_key", "paid_at"])

        elif status_value == "CANCELED" and payment.status == "done":
            payment.status = "cancelled"
            payment.save(update_fields=["status"])

        elif status_value in ("ABORTED", "EXPIRED") and payment.status == "pending":
            payment.status = "failed"
            payment.save(update_fields=["status"])

        return Response({"detail": "ok"}, status=status.HTTP_200_OK)


class PaymentListView(generics.ListAPIView):
    """내 결제 내역"""

    serializer_class = PaymentSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        if self.request.user.role == "admin":
            return Payment.objects.all()
        return Payment.objects.filter(user=self.request.user)


class PaymentCancelView(APIView):
    """결제 취소 (User)"""

    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, pk):
        try:
            payment = Payment.objects.get(pk=pk, user=request.user, status="done")
        except Payment.DoesNotExist:
            return Response(
                {"detail": "취소 가능한 결제를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not payment.toss_payment_key:
            return Response(
                {"detail": "PG 결제 정보가 없어 취소할 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cancel_reason = request.data.get("reason", "사용자 요청에 의한 취소")
        result = TossPaymentsService.cancel_payment(
            payment_key=payment.toss_payment_key,
            cancel_reason=cancel_reason,
        )

        if result["success"]:
            payment.status = "cancelled"
            payment.save(update_fields=["status"])
            return Response(PaymentSerializer(payment).data)

        return Response(
            {"detail": "결제 취소 실패", "error": result["error"]},
            status=status.HTTP_400_BAD_REQUEST,
        )
