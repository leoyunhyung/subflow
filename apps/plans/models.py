from django.db import models


class Plan(models.Model):
    class Tier(models.TextChoices):
        STARTER = "starter", "Starter"
        PRO = "pro", "Pro"
        ENTERPRISE = "enterprise", "Enterprise"

    class BillingCycle(models.TextChoices):
        MONTHLY = "monthly", "월간"
        YEARLY = "yearly", "연간"

    vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.CASCADE,
        related_name="plans",
    )
    name = models.CharField(max_length=100, verbose_name="플랜명")
    tier = models.CharField(max_length=20, choices=Tier.choices, verbose_name="티어")
    billing_cycle = models.CharField(
        max_length=10,
        choices=BillingCycle.choices,
        default=BillingCycle.MONTHLY,
        verbose_name="결제 주기",
    )
    price = models.PositiveIntegerField(verbose_name="가격 (원)")
    description = models.TextField(blank=True, verbose_name="설명")
    is_active = models.BooleanField(default=True, verbose_name="활성화")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "plans"
        verbose_name = "플랜"
        verbose_name_plural = "플랜"

    def __str__(self):
        return f"{self.vendor.company_name} - {self.name} ({self.get_tier_display()})"
