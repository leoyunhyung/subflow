import pytest
from unittest.mock import patch

from apps.payments.models import Payment
from apps.plans.models import Plan
from apps.subscriptions.models import Subscription

BASE_URL = "/api/v1/payments"


@pytest.fixture
def plan(vendor):
    return Plan.objects.create(
        vendor=vendor, name="Pro", tier="pro", billing_cycle="monthly", price=29000
    )


@pytest.fixture
def subscription(normal_user, plan):
    from django.utils import timezone
    from dateutil.relativedelta import relativedelta

    return Subscription.objects.create(
        user=normal_user, plan=plan, expires_at=timezone.now() + relativedelta(months=1)
    )


@pytest.fixture
def payment(normal_user, subscription):
    return Payment.objects.create(
        user=normal_user, subscription=subscription, amount=29000
    )


@pytest.fixture
def paid_payment(normal_user, subscription):
    from django.utils import timezone

    return Payment.objects.create(
        user=normal_user,
        subscription=subscription,
        amount=29000,
        status="done",
        toss_payment_key="toss_pk_test_123",
        paid_at=timezone.now(),
    )


@pytest.mark.django_db
class TestPayment:
    def test_create_payment(self, user_client, subscription):
        resp = user_client.post(
            f"{BASE_URL}/create/",
            {"subscription": subscription.pk, "amount": 29000},
        )
        assert resp.status_code == 201
        assert resp.data["status"] == "pending"

    def test_list_payments(self, user_client, payment):
        resp = user_client.get(f"{BASE_URL}/")
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1

    @patch("apps.payments.services.TossPaymentsService.confirm_payment")
    def test_confirm_payment_success(self, mock_confirm, user_client, payment):
        mock_confirm.return_value = {"success": True, "data": {"status": "DONE"}}
        resp = user_client.post(
            f"{BASE_URL}/confirm/",
            {
                "payment_key": "toss_pk_test_123",
                "order_id": str(payment.order_id),
                "amount": 29000,
            },
        )
        assert resp.status_code == 200
        assert resp.data["status"] == "done"

    @patch("apps.payments.services.TossPaymentsService.confirm_payment")
    def test_confirm_payment_failure(self, mock_confirm, user_client, payment):
        mock_confirm.return_value = {"success": False, "error": {"code": "FAILED"}}
        resp = user_client.post(
            f"{BASE_URL}/confirm/",
            {
                "payment_key": "toss_pk_test_fail",
                "order_id": str(payment.order_id),
                "amount": 29000,
            },
        )
        assert resp.status_code == 400

    def test_confirm_amount_mismatch(self, user_client, payment):
        resp = user_client.post(
            f"{BASE_URL}/confirm/",
            {
                "payment_key": "toss_pk_test",
                "order_id": str(payment.order_id),
                "amount": 99999,
            },
        )
        assert resp.status_code == 400


@pytest.mark.django_db
class TestPaymentWebhook:
    def test_webhook_done(self, api_client, payment):
        """Webhook으로 결제 완료 처리"""
        resp = api_client.post(
            f"{BASE_URL}/webhook/",
            {
                "eventType": "PAYMENT_STATUS_CHANGED",
                "data": {
                    "orderId": str(payment.order_id),
                    "paymentKey": "toss_pk_webhook_123",
                    "status": "DONE",
                },
            },
            format="json",
        )
        assert resp.status_code == 200
        payment.refresh_from_db()
        assert payment.status == "done"
        assert payment.toss_payment_key == "toss_pk_webhook_123"
        assert payment.paid_at is not None

    def test_webhook_canceled(self, api_client, paid_payment):
        """Webhook으로 결제 취소 처리"""
        resp = api_client.post(
            f"{BASE_URL}/webhook/",
            {
                "eventType": "PAYMENT_STATUS_CHANGED",
                "data": {
                    "orderId": str(paid_payment.order_id),
                    "paymentKey": paid_payment.toss_payment_key,
                    "status": "CANCELED",
                },
            },
            format="json",
        )
        assert resp.status_code == 200
        paid_payment.refresh_from_db()
        assert paid_payment.status == "cancelled"

    def test_webhook_invalid_order(self, api_client):
        """존재하지 않는 주문 ID로 webhook 호출"""
        resp = api_client.post(
            f"{BASE_URL}/webhook/",
            {
                "eventType": "PAYMENT_STATUS_CHANGED",
                "data": {
                    "orderId": "00000000-0000-0000-0000-000000000000",
                    "status": "DONE",
                },
            },
            format="json",
        )
        assert resp.status_code == 404


@pytest.mark.django_db
class TestPaymentCancel:
    @patch("apps.payments.services.TossPaymentsService.cancel_payment")
    def test_cancel_success(self, mock_cancel, user_client, paid_payment):
        mock_cancel.return_value = {"success": True, "data": {}}
        resp = user_client.post(
            f"{BASE_URL}/{paid_payment.pk}/cancel/",
            {"reason": "테스트 취소"},
        )
        assert resp.status_code == 200
        assert resp.data["status"] == "cancelled"

    @patch("apps.payments.services.TossPaymentsService.cancel_payment")
    def test_cancel_failure(self, mock_cancel, user_client, paid_payment):
        mock_cancel.return_value = {"success": False, "error": {"code": "FAILED"}}
        resp = user_client.post(f"{BASE_URL}/{paid_payment.pk}/cancel/")
        assert resp.status_code == 400

    def test_cancel_pending_payment_fails(self, user_client, payment):
        """pending 상태의 결제는 취소 불가"""
        resp = user_client.post(f"{BASE_URL}/{payment.pk}/cancel/")
        assert resp.status_code == 404
