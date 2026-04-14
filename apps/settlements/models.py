from django.db import models


class SettlementRate(models.Model):
    """벤더별 정산율 설정"""

    vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.CASCADE,
        related_name="settlement_rates",
    )
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name="수수료율 (%)",
        help_text="플랫폼 수수료 비율",
    )
    effective_date = models.DateField(
        verbose_name="적용 시작일",
        help_text="이 날짜부터 적용되는 수수료율",
    )
    memo = models.TextField(blank=True, verbose_name="메모")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "settlement_rates"
        verbose_name = "정산율"
        verbose_name_plural = "정산율"
        ordering = ["-effective_date"]
        unique_together = ("vendor", "effective_date")

    def __str__(self):
        return f"{self.vendor.company_name} - {self.commission_rate}% (from {self.effective_date})"

    @classmethod
    def get_current_rate(cls, vendor, target_date):
        """특정 날짜에 적용되는 정산율 조회"""
        return cls.objects.filter(
            vendor=vendor,
            effective_date__lte=target_date,
        ).order_by("-effective_date").first()


class Settlement(models.Model):
    """일별 벤더별 정산 요약 (DailySettlement)"""

    class Status(models.TextChoices):
        PENDING = "pending", "정산 대기"
        COMPLETED = "completed", "정산 완료"

    vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.CASCADE,
        related_name="settlements",
    )
    settlement_rate = models.ForeignKey(
        SettlementRate,
        on_delete=models.SET_NULL,
        null=True,
        related_name="settlements",
        verbose_name="적용된 정산율",
    )
    period_start = models.DateField(verbose_name="정산 시작일")
    period_end = models.DateField(verbose_name="정산 종료일")
    total_sales = models.PositiveIntegerField(default=0, verbose_name="총 매출")
    commission = models.PositiveIntegerField(default=0, verbose_name="수수료")
    payout_amount = models.PositiveIntegerField(default=0, verbose_name="정산 금액")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="상태",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True, verbose_name="정산 완료일")

    class Meta:
        db_table = "settlements"
        verbose_name = "정산"
        verbose_name_plural = "정산"
        ordering = ["-period_start"]
        unique_together = ("vendor", "period_start", "period_end")

    def __str__(self):
        return f"{self.vendor.company_name} ({self.period_start}~{self.period_end})"

    def mark_completed(self):
        from django.utils import timezone
        self.status = self.Status.COMPLETED
        self.settled_at = timezone.now()
        self.save(update_fields=["status", "settled_at"])


class UserSettlement(models.Model):
    """유저별 정산 상세"""

    settlement = models.ForeignKey(
        Settlement,
        on_delete=models.CASCADE,
        related_name="user_settlements",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="user_settlements",
    )
    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.SET_NULL,
        null=True,
        related_name="user_settlements",
    )
    amount = models.PositiveIntegerField(verbose_name="결제 금액")
    commission = models.PositiveIntegerField(verbose_name="수수료")
    payout = models.PositiveIntegerField(verbose_name="정산 금액")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_settlements"
        verbose_name = "유저별 정산"
        verbose_name_plural = "유저별 정산"
        unique_together = ("settlement", "payment")

    def __str__(self):
        username = self.user.username if self.user else "unknown"
        return f"{username} - {self.amount}원 (수수료: {self.commission}원)"


class SettlementHistory(models.Model):
    """정산 실행 이력 — 재계산 및 감사 추적"""

    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "성공"
        FAILED = "FAILED", "실패"

    period_start = models.DateField(verbose_name="정산 시작일")
    period_end = models.DateField(verbose_name="정산 종료일")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.FAILED,
    )
    executed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="executed_settlements",
    )
    expected_settlements = models.IntegerField(default=0, verbose_name="예상 정산 건수")
    actual_settlements = models.IntegerField(default=0, verbose_name="실제 정산 건수")
    expected_user_settlements = models.IntegerField(default=0, verbose_name="예상 유저 정산 건수")
    actual_user_settlements = models.IntegerField(default=0, verbose_name="실제 유저 정산 건수")
    total_commission = models.PositiveIntegerField(default=0, verbose_name="총 수수료")
    is_verified = models.BooleanField(
        default=False,
        verbose_name="정합성 검증 통과",
        help_text="예상값과 실제값이 일치하는지 여부",
    )
    processed_seconds = models.FloatField(null=True, blank=True, verbose_name="처리 소요시간(초)")
    error_message = models.TextField(blank=True, verbose_name="에러 메시지")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "settlement_histories"
        verbose_name = "정산 실행 이력"
        verbose_name_plural = "정산 실행 이력"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.period_start}~{self.period_end} - {self.get_status_display()}"

    @property
    def integrity_message(self):
        if self.is_verified:
            return "정상 처리 완료"
        messages = []
        if self.expected_settlements != self.actual_settlements:
            diff = self.expected_settlements - self.actual_settlements
            messages.append(f"정산 {abs(diff)}건 {'누락' if diff > 0 else '초과'}")
        if self.expected_user_settlements != self.actual_user_settlements:
            diff = self.expected_user_settlements - self.actual_user_settlements
            messages.append(f"유저 정산 {abs(diff)}건 {'누락' if diff > 0 else '초과'}")
        return " / ".join(messages) if messages else "불일치 원인 미확인"
