from django.conf import settings
from django.db import models


class Subscription(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "활성"
        CANCELLED = "cancelled", "해지"
        EXPIRED = "expired", "만료"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        "plans.Plan",
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="상태",
    )
    started_at = models.DateTimeField(auto_now_add=True, verbose_name="시작일")
    expires_at = models.DateTimeField(verbose_name="만료일")
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="해지일")

    class Meta:
        db_table = "subscriptions"
        verbose_name = "구독"
        verbose_name_plural = "구독"

    def __str__(self):
        return f"{self.user.username} → {self.plan.name}"
