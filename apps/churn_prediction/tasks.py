"""
Celery 태스크.

구조:
    1) predict_churn_batch        -- 메인: 전체 active 구독 대상 배치 (Celery Beat 스케줄)
    2) predict_churn_for_subscription -- 단건 비동기 실행 (관리자 "다시 계산" 트리거)

정합성 검증 패턴:
    settlements.tasks.generate_settlements 와 동일하게
      a) 초기 상태 RUNNING 으로 ChurnPredictionRun 생성
      b) 예상 건수 사전 계산
      c) 실제 처리
      d) expected == actual + failed 여부로 is_verified 판정
      e) 실패 / 부분 실패 / 성공 을 status 로 기록
"""
from __future__ import annotations

import logging
import time

from celery import shared_task
from django.utils import timezone

from apps.churn_prediction.models import ChurnPredictionRun
from apps.churn_prediction.services.feature_extractor import iter_active_subscriptions
from apps.churn_prediction.services.predictor import (
    estimate_cost,
    predict_for_subscription,
)

logger = logging.getLogger(__name__)


@shared_task
def predict_churn_batch(executed_by_id: int | None = None):
    """
    전체 active 구독에 대한 이탈 예측 배치.
    Celery Beat 로 하루 1회 실행 (config/settings 에서 스케줄 등록).
    """
    from apps.accounts.models import User
    from apps.subscriptions.models import Subscription

    today = timezone.localdate()
    executed_by = (
        User.objects.filter(pk=executed_by_id).first() if executed_by_id else None
    )

    run = ChurnPredictionRun.objects.create(
        prediction_date=today,
        status=ChurnPredictionRun.Status.RUNNING,
        trigger_type=(
            ChurnPredictionRun.TriggerType.MANUAL
            if executed_by_id
            else ChurnPredictionRun.TriggerType.SCHEDULED
        ),
        executed_by=executed_by,
    )

    start_time = time.time()

    try:
        # 1단계: 예상 건수 사전 집계 (active 구독 전체 수)
        expected = Subscription.objects.filter(
            status=Subscription.Status.ACTIVE
        ).count()
        run.expected_count = expected
        run.save(update_fields=["expected_count"])

        if expected == 0:
            run.status = ChurnPredictionRun.Status.SUCCESS
            run.is_verified = True
            run.processed_seconds = time.time() - start_time
            run.save()
            logger.info("예측 대상 active 구독 없음")
            return 0

        # 2단계: 실제 처리 — 구독 단위로 독립 처리 (한 건 실패가 전체 배치를 막지 않도록)
        actual = 0
        skipped = 0
        failed = 0
        total_in = 0
        total_out = 0

        for subscription in iter_active_subscriptions():
            try:
                result = predict_for_subscription(subscription)
            except Exception as e:  # noqa: BLE001 — 어떤 예외든 배치는 계속 진행
                logger.exception("sub#%s 예측 중 예외", subscription.pk)
                failed += 1
                continue

            if result.skipped:
                skipped += 1
            elif result.ok:
                actual += 1
                total_in += result.input_tokens
                total_out += result.output_tokens
            else:
                failed += 1

        processed = time.time() - start_time

        # 3단계: 정합성 검증
        handled = actual + skipped + failed
        is_verified = expected == handled

        if failed == 0 and is_verified:
            status = ChurnPredictionRun.Status.SUCCESS
        elif actual > 0 and failed > 0:
            status = ChurnPredictionRun.Status.PARTIAL
        elif actual == 0 and skipped == expected:
            # 전원 healthy — 이것도 성공으로 취급
            status = ChurnPredictionRun.Status.SUCCESS
        else:
            status = ChurnPredictionRun.Status.FAILED

        run.status = status
        run.actual_count = actual
        run.skipped_count = skipped
        run.failed_count = failed
        run.is_verified = is_verified
        run.processed_seconds = processed
        run.total_input_tokens = total_in
        run.total_output_tokens = total_out
        run.estimated_cost_usd = estimate_cost(total_in, total_out)
        run.save()

        logger.info(
            "이탈 예측 배치 완료: 예상=%d 실제=%d 스킵=%d 실패=%d verified=%s (%.2fs, $%s)",
            expected,
            actual,
            skipped,
            failed,
            is_verified,
            processed,
            run.estimated_cost_usd,
        )
        return actual

    except Exception as e:
        run.status = ChurnPredictionRun.Status.FAILED
        run.error_message = str(e)[:2000]
        run.processed_seconds = time.time() - start_time
        run.save()
        logger.exception("이탈 예측 배치 실패")
        raise


@shared_task
def predict_churn_for_subscription(subscription_id: int, executed_by_id: int | None = None):
    """
    단일 구독 예측 (관리자 즉시 재실행용).
    force=True 로 위험군 필터를 우회하여 항상 LLM 호출.
    """
    from apps.accounts.models import User
    from apps.subscriptions.models import Subscription

    try:
        subscription = Subscription.objects.select_related("plan", "user").get(
            pk=subscription_id
        )
    except Subscription.DoesNotExist:
        logger.warning("sub#%s 없음", subscription_id)
        return {"ok": False, "error": "subscription_not_found"}

    today = timezone.localdate()
    run = ChurnPredictionRun.objects.create(
        prediction_date=today,
        status=ChurnPredictionRun.Status.RUNNING,
        trigger_type=ChurnPredictionRun.TriggerType.MANUAL,
        executed_by=User.objects.filter(pk=executed_by_id).first() if executed_by_id else None,
        expected_count=1,
    )

    start_time = time.time()
    try:
        result = predict_for_subscription(subscription, force=True)

        if result.ok:
            run.status = ChurnPredictionRun.Status.SUCCESS
            run.actual_count = 1
            run.total_input_tokens = result.input_tokens
            run.total_output_tokens = result.output_tokens
            run.estimated_cost_usd = estimate_cost(
                result.input_tokens, result.output_tokens
            )
            run.is_verified = True
        else:
            run.status = ChurnPredictionRun.Status.FAILED
            run.failed_count = 1
            run.error_message = result.error[:2000]

        run.processed_seconds = time.time() - start_time
        run.save()

        return {
            "ok": result.ok,
            "prediction_id": result.prediction.id if result.prediction else None,
            "error": result.error,
        }

    except Exception as e:
        run.status = ChurnPredictionRun.Status.FAILED
        run.failed_count = 1
        run.error_message = str(e)[:2000]
        run.processed_seconds = time.time() - start_time
        run.save()
        logger.exception("sub#%s 단건 예측 실패", subscription_id)
        raise
