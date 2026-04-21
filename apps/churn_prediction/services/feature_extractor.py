"""
피처 추출 모듈.

역할:
    1) Subscription 한 건을 받아 LLM 에 넣을 피처 JSON 을 생성한다.
    2) 배치 실행 시 LLM 호출 비용을 줄이기 위한 **위험군 후보 필터링** 로직을 제공한다.

설계 근거:
    - LLM 은 피처 해석과 자연어 근거 생성에 강점이 있을 뿐, 피처 자체는 결정론적으로
      계산 가능. 피처 계산을 LLM 이 아닌 ORM 으로 수행해 비용과 변동성을 낮춘다.
    - N+1 을 피하기 위해 조회 시 select_related / annotate 를 사용.
    - 위험 피처 중 1개라도 임계치를 넘으면 LLM 호출 대상 (candidate).
      아예 건강한 구독은 LLM 호출 자체를 스킵 → 수만 건 배치에서 비용 제어.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

FEATURE_VERSION = "v1"

# 위험군 후보 필터 임계치 — 하나라도 걸리면 LLM 호출 대상
CANDIDATE_THRESHOLDS = {
    "payment_fail_count_90d": 1,        # 최근 90일 결제 실패 1건 이상
    "days_until_expiry": 14,            # 14일 이내 만료
    "cancellation_attempt_count": 1,    # 해지 시도 이력 있음
    "last_payment_days_ago": 45,        # 마지막 결제 45일 이상 경과
}


@dataclass
class ExtractedFeatures:
    """피처 추출 결과. dict 와 'candidate 여부' 를 함께 반환."""

    data: dict
    is_candidate: bool
    skip_reason: str = ""


def extract_features(subscription) -> ExtractedFeatures:
    """
    단일 구독에 대한 피처를 계산한다.

    Subscription 은 views / tasks 에서 select_related("plan", "user") 로
    프리페치된 상태를 가정한다 (N+1 방지).
    """
    from apps.payments.models import Payment

    now = timezone.now()
    today = now.date()
    since_90d = now - timedelta(days=90)

    # --- 결제 관련 집계 (한 번의 쿼리로) ---
    payment_agg = Payment.objects.filter(
        subscription=subscription,
        created_at__gte=since_90d,
    ).aggregate(
        success_count=Count("id", filter=Q(status=Payment.Status.DONE)),
        failed_count=Count("id", filter=Q(status=Payment.Status.FAILED)),
    )

    # 누적 결제 금액 (전체 기간)
    total_paid = Payment.objects.filter(
        subscription=subscription,
        status=Payment.Status.DONE,
    ).aggregate(
        total=Count("id"),
    )["total"]

    # 가장 최근 결제
    last_paid = (
        Payment.objects.filter(
            subscription=subscription,
            status=Payment.Status.DONE,
            paid_at__isnull=False,
        )
        .order_by("-paid_at")
        .values_list("paid_at", flat=True)
        .first()
    )
    last_payment_days_ago = (now - last_paid).days if last_paid else None

    # --- 구독 라이프사이클 ---
    sub_age_days = (now - subscription.started_at).days
    days_until_expiry = (subscription.expires_at - now).days

    # 해지 이력 — 현재는 Subscription.cancelled_at 유무로 판단.
    # 실제 운영이라면 별도 CancellationAttempt 로그 테이블이 있을 것.
    cancellation_attempt_count = 1 if subscription.cancelled_at else 0

    plan = subscription.plan
    features = {
        # 구독
        "subscription_age_days": sub_age_days,
        "days_until_expiry": days_until_expiry,
        "status": subscription.status,
        # 결제
        "payment_fail_count_90d": payment_agg["failed_count"] or 0,
        "payment_success_count_90d": payment_agg["success_count"] or 0,
        "total_payment_count": total_paid or 0,
        "last_payment_days_ago": last_payment_days_ago,
        # 해지
        "cancellation_attempt_count": cancellation_attempt_count,
        # 플랜
        "plan_tier": plan.tier,
        "billing_cycle": plan.billing_cycle,
        "plan_price": plan.price,
    }

    is_candidate, reason = _is_candidate(features, subscription)
    return ExtractedFeatures(
        data=features,
        is_candidate=is_candidate,
        skip_reason=reason,
    )


def _is_candidate(features: dict, subscription) -> tuple[bool, str]:
    """LLM 호출 대상인지 판정. 아니면 스킵 사유 문자열 반환."""
    # 해지/만료 된 구독은 예측할 필요 없음
    if subscription.status != "active":
        return False, f"status={subscription.status}"

    if features["payment_fail_count_90d"] >= CANDIDATE_THRESHOLDS["payment_fail_count_90d"]:
        return True, ""
    if features["days_until_expiry"] <= CANDIDATE_THRESHOLDS["days_until_expiry"]:
        return True, ""
    if features["cancellation_attempt_count"] >= CANDIDATE_THRESHOLDS["cancellation_attempt_count"]:
        return True, ""

    last = features["last_payment_days_ago"]
    if last is not None and last >= CANDIDATE_THRESHOLDS["last_payment_days_ago"]:
        return True, ""

    return False, "healthy"


def iter_active_subscriptions():
    """
    배치 대상 active 구독 쿼리셋 반환.
    iterator() 로 메모리 효율 확보 (수만 건 대비).
    """
    from apps.subscriptions.models import Subscription

    return (
        Subscription.objects.filter(status=Subscription.Status.ACTIVE)
        .select_related("plan", "user")
        .iterator(chunk_size=500)
    )
