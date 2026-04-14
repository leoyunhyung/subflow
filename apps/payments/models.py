import uuid

from django.conf import settings
from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "대기"
        DONE = "done", "완료"
        FAILED = "failed", "실패"
        CANCELLED = "cancelled", "취소"

    order_id = models.UUIDField(default=uuid.uuid4, unique=True, verbose_name="주문 ID")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    subscription = models.ForeignKey(
        "subscriptions.Subscription",
        on_delete=models.SET_NULL,
        null=True,
        related_name="payments",
    )
    amount = models.PositiveIntegerField(verbose_name="결제 금액")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="상태",
    )
    toss_payment_key = models.CharField(
        max_length=200, blank=True, verbose_name="토스 paymentKey"
    )
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="결제 완료 시각")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payments"
        verbose_name = "결제"
        verbose_name_plural = "결제"

    def __str__(self):
        return f"Payment {self.order_id} - {self.get_status_display()}"
