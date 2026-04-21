"""
구독 이탈 예측 도메인 모델.

설계 원칙:
    1) 예측 결과(ChurnPrediction)와 입력 피처 스냅샷(ChurnFeatureSnapshot)을 분리 저장.
       → LLM 호출 시점의 입력을 그대로 보관하여 재현 / 디버깅 / 프롬프트 개편 전후 비교 가능.
    2) 실행 이력(ChurnPredictionRun)은 settlements 앱의 SettlementHistory와 동일한 패턴.
       → 예상 건수, 실제 건수, 소요시간, 에러 메시지를 남겨 감사 추적.
    3) 모델/프롬프트 버전을 함께 기록 → 나중에 "어떤 프롬프트 / 어떤 모델로 나온 결과인지" 추적 가능.
    4) unique_together 로 같은 구독에 대한 같은 날짜 중복 예측 방지.
"""
from django.conf import settings
from django.db import models


class ChurnRiskLevel(models.TextChoices):
    LOW = "low", "낮음"
    MEDIUM = "medium", "보통"
    HIGH = "high", "높음"
    CRITICAL = "critical", "심각"


class ChurnFeatureSnapshot(models.Model):
    """
    LLM 호출 시점의 입력 피처를 그대로 기록.

    LLM 응답이 불안정하다는 비판에 대한 방어 장치:
    "동일한 피처 스냅샷을 재투입하면 동일한 예측을 재현할 수 있어야 한다"
    -> 프롬프트 / 모델 버전 고정 시 재현 가능.

    저장되는 피처 예시 (feature_data JSON):
        {
            "subscription_age_days": 45,
            "days_until_expiry": 12,
            "payment_fail_count_90d": 2,
            "payment_success_count_90d": 3,
            "total_paid_amount": 89000,
            "last_payment_days_ago": 35,
            "cancellation_attempt_count": 1,
            "plan_tier": "pro",
            "billing_cycle": "monthly"
        }
    """

    subscription = models.ForeignKey(
        "subscriptions.Subscription",
        on_delete=models.CASCADE,
        related_name="feature_snapshots",
        verbose_name="구독",
    )
    feature_data = models.JSONField(
        verbose_name="피처 데이터",
        help_text="LLM 입력으로 들어간 피처 전체 JSON",
    )
    feature_version = models.CharField(
        max_length=20,
        default="v1",
        verbose_name="피처 버전",
        help_text="피처 추출 로직 버전 — 피처 정의가 바뀌면 증가",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "churn_feature_snapshots"
        verbose_name = "이탈 예측 피처 스냅샷"
        verbose_name_plural = "이탈 예측 피처 스냅샷"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["subscription", "-created_at"]),
        ]

    def __str__(self):
        return f"FeatureSnapshot#{self.pk} for sub#{self.subscription_id}"


class ChurnPrediction(models.Model):
    """
    특정 구독에 대한 이탈 예측 결과 한 건.

    하루에 한 구독당 1건만 생성되도록 unique_together 로 제약
    (배치 실행 중복 방지 + 관리자 수동 재실행 시 기존 건 삭제 후 재생성).
    """

    subscription = models.ForeignKey(
        "subscriptions.Subscription",
        on_delete=models.CASCADE,
        related_name="churn_predictions",
        verbose_name="구독",
    )
    feature_snapshot = models.OneToOneField(
        ChurnFeatureSnapshot,
        on_delete=models.CASCADE,
        related_name="prediction",
        verbose_name="입력 피처 스냅샷",
    )

    # === LLM 예측 결과 ===
    risk_score = models.PositiveSmallIntegerField(
        verbose_name="이탈 위험도 (0-100)",
        help_text="100에 가까울수록 이탈 가능성 높음",
    )
    risk_level = models.CharField(
        max_length=10,
        choices=ChurnRiskLevel.choices,
        verbose_name="위험 등급",
    )
    reasoning = models.TextField(
        verbose_name="판단 근거",
        help_text="LLM이 제시한 이탈 위험 판단 근거",
    )
    recommended_actions = models.JSONField(
        verbose_name="리텐션 액션 추천",
        help_text="LLM이 추천한 리텐션 액션 리스트",
        default=list,
    )

    # === LLM 호출 메타데이터 ===
    llm_provider = models.CharField(
        max_length=30,
        verbose_name="LLM 제공자",
        help_text="claude / openai / gemini 등 — Gateway 교체 가능성 대비",
    )
    llm_model = models.CharField(
        max_length=60,
        verbose_name="LLM 모델명",
        help_text="claude-opus-4-5 등 구체 모델명",
    )
    prompt_version = models.CharField(
        max_length=20,
        default="v1",
        verbose_name="프롬프트 버전",
    )
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0, verbose_name="LLM 응답 지연(ms)")

    # === 감사 / 디버깅용 ===
    raw_response = models.JSONField(
        verbose_name="LLM 원본 응답",
        help_text="파싱 전 원본. 스키마 변경 / 회귀 분석 시 참고용.",
        default=dict,
    )
    prediction_date = models.DateField(
        verbose_name="예측 기준일",
        help_text="같은 구독 + 같은 날짜 조합은 1건만 허용",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "churn_predictions"
        verbose_name = "이탈 예측"
        verbose_name_plural = "이탈 예측"
        ordering = ["-created_at"]
        unique_together = ("subscription", "prediction_date")
        indexes = [
            models.Index(fields=["risk_level", "-prediction_date"]),
            models.Index(fields=["-prediction_date"]),
        ]

    def __str__(self):
        return (
            f"sub#{self.subscription_id} "
            f"risk={self.risk_score}({self.get_risk_level_display()}) "
            f"@{self.prediction_date}"
        )

    @classmethod
    def latest_for(cls, subscription):
        """특정 구독의 가장 최근 예측 결과."""
        return (
            cls.objects.filter(subscription=subscription)
            .order_by("-prediction_date")
            .first()
        )


class ChurnPredictionRun(models.Model):
    """
    이탈 예측 배치 실행 이력.

    settlements.SettlementHistory 와 동일한 패턴:
      - 초기 상태를 FAILED 로 생성
      - 예상 건수 / 실제 건수 사전 기록
      - 완료 시점에 정합성 (expected == actual) 검증
      - 실패 시 error_message 에 스택 요약 저장
    """

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "실행 중"
        SUCCESS = "SUCCESS", "성공"
        PARTIAL = "PARTIAL", "부분 성공"
        FAILED = "FAILED", "실패"

    class TriggerType(models.TextChoices):
        SCHEDULED = "scheduled", "스케줄 배치"
        MANUAL = "manual", "관리자 수동"

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    trigger_type = models.CharField(
        max_length=10,
        choices=TriggerType.choices,
        default=TriggerType.SCHEDULED,
        verbose_name="실행 유형",
    )
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="executed_churn_runs",
        verbose_name="실행자",
        help_text="수동 실행 시 해당 관리자, 배치면 NULL",
    )
    prediction_date = models.DateField(verbose_name="예측 기준일")

    expected_count = models.IntegerField(default=0, verbose_name="예상 예측 건수")
    actual_count = models.IntegerField(default=0, verbose_name="실제 예측 건수")
    skipped_count = models.IntegerField(
        default=0, verbose_name="필터로 제외된 건수",
        help_text="위험군 후보 필터링으로 LLM 호출 생략된 건수 — 비용 제어 근거",
    )
    failed_count = models.IntegerField(default=0, verbose_name="LLM 호출 실패 건수")
    is_verified = models.BooleanField(
        default=False,
        verbose_name="정합성 검증 통과",
        help_text="expected_count == actual_count + failed_count 여부",
    )
    processed_seconds = models.FloatField(null=True, blank=True, verbose_name="소요시간(초)")

    total_input_tokens = models.PositiveBigIntegerField(default=0)
    total_output_tokens = models.PositiveBigIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0,
        verbose_name="예상 비용 (USD)",
    )

    error_message = models.TextField(blank=True, verbose_name="에러 메시지")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "churn_prediction_runs"
        verbose_name = "이탈 예측 실행 이력"
        verbose_name_plural = "이탈 예측 실행 이력"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-prediction_date"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return (
            f"ChurnRun {self.prediction_date} "
            f"[{self.get_status_display()}] "
            f"{self.actual_count}/{self.expected_count}"
        )

    @property
    def integrity_message(self):
        """SettlementHistory.integrity_message 와 동일한 역할."""
        if self.is_verified:
            return "정상 처리 완료"

        handled = self.actual_count + self.failed_count
        if self.expected_count != handled:
            diff = self.expected_count - handled
            return (
                f"{abs(diff)}건 "
                f"{'미처리' if diff > 0 else '초과 처리'} — 조사 필요"
            )
        return "정합성 불일치 (원인 미확인)"
