import pytest
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from apps.payments.models import Payment
from apps.plans.models import Plan
from apps.settlements.models import Settlement, SettlementHistory, SettlementRate, UserSettlement
from apps.settlements.tasks import generate_settlements
from apps.subscriptions.models import Subscription

BASE_URL = "/api/v1/settlements"


@pytest.fixture
def plan(vendor):
    return Plan.objects.create(
        vendor=vendor, name="Pro", tier="pro", billing_cycle="monthly", price=29000
    )


@pytest.fixture
def settlement_rate(vendor):
    return SettlementRate.objects.create(
        vendor=vendor,
        commission_rate=15,
        effective_date="2026-01-01",
        memo="2026년 수수료율",
    )


@pytest.fixture
def paid_payment(normal_user, vendor, plan):
    sub = Subscription.objects.create(
        user=normal_user, plan=plan, expires_at=timezone.now() + relativedelta(months=1)
    )
    return Payment.objects.create(
        user=normal_user,
        subscription=sub,
        amount=29000,
        status="done",
        paid_at=timezone.now(),
    )


@pytest.fixture
def settlement(vendor):
    return Settlement.objects.create(
        vendor=vendor,
        period_start="2026-03-01",
        period_end="2026-03-31",
        total_sales=100000,
        commission=10000,
        payout_amount=90000,
    )


@pytest.mark.django_db
class TestSettlement:
    def test_admin_list_settlements(self, admin_client, settlement):
        resp = admin_client.get(f"{BASE_URL}/")
        assert resp.status_code == 200
        assert len(resp.data["results"]) >= 1

    def test_vendor_sees_own_settlements(self, vendor_client, settlement):
        resp = vendor_client.get(f"{BASE_URL}/")
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1

    def test_admin_completes_settlement(self, admin_client, settlement):
        resp = admin_client.post(f"{BASE_URL}/{settlement.pk}/complete/")
        assert resp.status_code == 200
        assert resp.data["status"] == "completed"
        assert resp.data["settled_at"] is not None

    def test_vendor_cannot_complete(self, vendor_client, settlement):
        resp = vendor_client.post(f"{BASE_URL}/{settlement.pk}/complete/")
        assert resp.status_code == 403

    def test_generate_returns_202(self, admin_client):
        resp = admin_client.post(
            f"{BASE_URL}/generate/",
            {"period_start": "2026-04-01", "period_end": "2026-04-14"},
        )
        assert resp.status_code == 202

    def test_generate_requires_dates(self, admin_client):
        resp = admin_client.post(f"{BASE_URL}/generate/", {})
        assert resp.status_code == 400


@pytest.mark.django_db
class TestSettlementHistory:
    def test_admin_views_history(self, admin_client):
        SettlementHistory.objects.create(
            period_start="2026-03-01",
            period_end="2026-03-31",
            status="SUCCESS",
            is_verified=True,
        )
        resp = admin_client.get(f"{BASE_URL}/history/")
        assert resp.status_code == 200
        assert len(resp.data["results"]) >= 1

    def test_vendor_cannot_view_history(self, vendor_client):
        resp = vendor_client.get(f"{BASE_URL}/history/")
        assert resp.status_code == 403


@pytest.mark.django_db
class TestSettlementRate:
    def test_admin_creates_rate(self, admin_client, vendor):
        resp = admin_client.post(
            f"{BASE_URL}/rates/",
            {
                "vendor": vendor.pk,
                "commission_rate": "12.50",
                "effective_date": "2026-04-01",
                "memo": "4월 수수료율",
            },
        )
        assert resp.status_code == 201
        assert resp.data["commission_rate"] == "12.50"

    def test_get_current_rate(self, vendor, settlement_rate):
        from datetime import date
        rate = SettlementRate.get_current_rate(vendor, date(2026, 6, 1))
        assert rate is not None
        assert rate.commission_rate == 15


@pytest.mark.django_db
class TestGenerateSettlementsTask:
    def test_generate_with_rate(self, paid_payment, vendor, settlement_rate):
        """SettlementRate가 있을 때 해당 수수료율(15%)이 적용되는지 검증"""
        today = timezone.now().date()
        start = today.replace(day=1).isoformat()
        end = today.isoformat()

        count = generate_settlements(start, end)
        assert count == 1

        s = Settlement.objects.get(vendor=vendor)
        assert s.total_sales == 29000
        assert s.commission == 4350  # 15%
        assert s.payout_amount == 24650
        assert s.settlement_rate == settlement_rate

        # UserSettlement 검증
        user_settlements = UserSettlement.objects.filter(settlement=s)
        assert user_settlements.count() == 1
        us = user_settlements.first()
        assert us.amount == 29000
        assert us.commission == 4350
        assert us.payout == 24650

    def test_generate_without_rate_uses_vendor_rate(self, paid_payment, vendor):
        """SettlementRate가 없으면 vendor.commission_rate(10%)이 적용되는지 검증"""
        today = timezone.now().date()
        start = today.replace(day=1).isoformat()
        end = today.isoformat()

        count = generate_settlements(start, end)
        assert count == 1

        s = Settlement.objects.get(vendor=vendor)
        assert s.commission == 2900  # vendor default 10%
        assert s.settlement_rate is None

    def test_integrity_verification(self, paid_payment, vendor):
        """정합성 검증: 예상값과 실제값이 일치하는지 확인"""
        today = timezone.now().date()
        start = today.replace(day=1).isoformat()
        end = today.isoformat()

        generate_settlements(start, end)

        history = SettlementHistory.objects.latest("created_at")
        assert history.status == "SUCCESS"
        assert history.is_verified is True
        assert history.expected_settlements == 1
        assert history.actual_settlements == 1
        assert history.expected_user_settlements == 1
        assert history.actual_user_settlements == 1
        assert history.processed_seconds is not None
        assert history.processed_seconds > 0

    def test_no_payments_generates_nothing(self, vendor):
        """결제 건이 없으면 정산이 생성되지 않는지 확인"""
        count = generate_settlements("2026-01-01", "2026-01-31")
        assert count == 0

        history = SettlementHistory.objects.latest("created_at")
        assert history.status == "SUCCESS"
        assert history.is_verified is True
        assert history.expected_settlements == 0

    def test_history_records_user_id(self, paid_payment, vendor, admin_user):
        """실행자 정보가 기록되는지 확인"""
        today = timezone.now().date()
        start = today.replace(day=1).isoformat()
        end = today.isoformat()

        generate_settlements(start, end, user_id=admin_user.pk)

        history = SettlementHistory.objects.latest("created_at")
        assert history.executed_by == admin_user
