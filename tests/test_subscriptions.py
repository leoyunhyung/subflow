import pytest

from apps.plans.models import Plan
from apps.subscriptions.models import Subscription

BASE_URL = "/api/v1/subscriptions"


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


@pytest.mark.django_db
class TestSubscription:
    def test_create_subscription(self, user_client, plan):
        resp = user_client.post(f"{BASE_URL}/", {"plan": plan.pk})
        assert resp.status_code == 201
        assert resp.data["status"] == "active"

    def test_list_my_subscriptions(self, user_client, subscription):
        resp = user_client.get(f"{BASE_URL}/")
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1

    def test_cancel_subscription(self, user_client, subscription):
        resp = user_client.post(f"{BASE_URL}/{subscription.pk}/cancel/")
        assert resp.status_code == 200
        assert resp.data["status"] == "cancelled"

    def test_vendor_cannot_subscribe(self, vendor_client, plan):
        resp = vendor_client.post(f"{BASE_URL}/", {"plan": plan.pk})
        assert resp.status_code == 403
