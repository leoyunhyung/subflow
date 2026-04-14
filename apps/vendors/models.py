from django.conf import settings
from django.db import models


class Vendor(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "승인 대기"
        APPROVED = "approved", "승인"
        REJECTED = "rejected", "거절"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vendor_profile",
    )
    company_name = models.CharField(max_length=100, verbose_name="회사명")
    business_number = models.CharField(max_length=20, verbose_name="사업자등록번호")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="승인 상태",
    )
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="수수료율 (%)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vendors"
        verbose_name = "벤더"
        verbose_name_plural = "벤더"

    def __str__(self):
        return self.company_name
