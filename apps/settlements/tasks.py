import logging
import time
from datetime import datetime
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.db.models import Sum

logger = logging.getLogger(__name__)


@shared_task
def generate_settlements(period_start: str, period_end: str, user_id: int = None):
    """
    주어진 기간의 벤더별 정산 데이터를 생성한다.

    3계층 구조:
      1) SettlementRate — 벤더별 적용 수수료율 조회
      2) Settlement (DailySettlement) — 벤더별 기간 정산 요약
      3) UserSettlement — 유저별 결제 건 상세 정산

    정합성 검증:
      - 정산 전 예상값(벤더 수, 결제 건수)을 사전 계산
      - 실제 생성 결과와 비교하여 불일치 즉시 감지
      - SettlementHistory에 실행 이력 기록
    """
    from apps.accounts.models import User
    from apps.payments.models import Payment
    from apps.settlements.models import (
        Settlement,
        SettlementHistory,
        SettlementRate,
        UserSettlement,
    )
    from apps.vendors.models import Vendor

    start = datetime.strptime(period_start, "%Y-%m-%d").date()
    end = datetime.strptime(period_end, "%Y-%m-%d").date()

    executed_by = None
    if user_id:
        executed_by = User.objects.filter(pk=user_id).first()

    # SettlementHistory 생성 (초기 상태: FAILED)
    history = SettlementHistory.objects.create(
        period_start=start,
        period_end=end,
        status=SettlementHistory.Status.FAILED,
        executed_by=executed_by,
    )

    start_time = time.time()

    try:
        vendors = Vendor.objects.filter(status="approved")

        # === 1단계: 예상값 사전 계산 ===
        expected_settlements = 0
        expected_user_settlements = 0

        for vendor in vendors:
            payment_count = Payment.objects.filter(
                subscription__plan__vendor=vendor,
                status="done",
                paid_at__date__gte=start,
                paid_at__date__lte=end,
            ).count()

            if payment_count > 0:
                expected_settlements += 1
                expected_user_settlements += payment_count

        history.expected_settlements = expected_settlements
        history.expected_user_settlements = expected_user_settlements
        history.save(update_fields=["expected_settlements", "expected_user_settlements"])

        if expected_settlements == 0:
            history.status = SettlementHistory.Status.SUCCESS
            history.is_verified = True
            history.processed_seconds = time.time() - start_time
            history.save()
            logger.info("No settlements to generate for %s ~ %s", period_start, period_end)
            return 0

        # === 2단계: 실제 정산 계산 및 저장 ===
        actual_settlements = 0
        actual_user_settlements = 0
        total_commission = 0

        with transaction.atomic():
            for vendor in vendors:
                payments = Payment.objects.filter(
                    subscription__plan__vendor=vendor,
                    status="done",
                    paid_at__date__gte=start,
                    paid_at__date__lte=end,
                ).select_related("user", "subscription__plan")

                if not payments.exists():
                    continue

                # 적용할 정산율 조회 (SettlementRate → fallback: vendor.commission_rate)
                rate_obj = SettlementRate.get_current_rate(vendor, end)
                if rate_obj:
                    rate = rate_obj.commission_rate
                elif vendor.commission_rate:
                    rate = vendor.commission_rate
                    rate_obj = None
                else:
                    rate = Decimal("10")
                    rate_obj = None

                total_sales = payments.aggregate(total=Sum("amount"))["total"] or 0
                commission = int(total_sales * rate / 100)
                payout = total_sales - commission

                # Settlement (벤더별 요약) 생성
                settlement = Settlement.objects.create(
                    vendor=vendor,
                    settlement_rate=rate_obj,
                    period_start=start,
                    period_end=end,
                    total_sales=total_sales,
                    commission=commission,
                    payout_amount=payout,
                )
                actual_settlements += 1
                total_commission += commission

                # UserSettlement (유저별 상세) 생성
                for payment in payments:
                    user_commission = int(payment.amount * rate / 100)
                    user_payout = payment.amount - user_commission

                    UserSettlement.objects.create(
                        settlement=settlement,
                        user=payment.user,
                        payment=payment,
                        amount=payment.amount,
                        commission=user_commission,
                        payout=user_payout,
                    )
                    actual_user_settlements += 1

        # === 3단계: 정합성 검증 ===
        is_verified = (
            expected_settlements == actual_settlements
            and expected_user_settlements == actual_user_settlements
        )

        processed_seconds = time.time() - start_time

        history.status = SettlementHistory.Status.SUCCESS
        history.actual_settlements = actual_settlements
        history.actual_user_settlements = actual_user_settlements
        history.total_commission = total_commission
        history.is_verified = is_verified
        history.processed_seconds = processed_seconds
        history.save()

        logger.info(
            "Generated %d settlements (%d user details) for %s ~ %s [verified=%s, %.2fs]",
            actual_settlements,
            actual_user_settlements,
            period_start,
            period_end,
            is_verified,
            processed_seconds,
        )
        return actual_settlements

    except Exception as e:
        history.status = SettlementHistory.Status.FAILED
        history.error_message = str(e)
        history.processed_seconds = time.time() - start_time
        history.save()
        logger.error("Settlement generation failed: %s", e)
        raise


@shared_task
def expire_subscriptions():
    """만료된 구독을 자동으로 expired 처리한다."""
    from django.utils import timezone

    from apps.subscriptions.models import Subscription

    expired = Subscription.objects.filter(
        status="active",
        expires_at__lt=timezone.now(),
    ).update(status="expired")

    logger.info("Expired %d subscriptions", expired)
    return expired
