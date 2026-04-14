import pytest

from apps.plans.models import Plan

BASE_URL = "/api/v1/plans"


@pytest.fixture
def plan(vendor):
    return Plan.objects.create(
        vendor=vendor,
        name="Pro Plan",
        tier="pro",
        billing_cycle="monthly",
        price=29000,
        description="프로 플랜입니다.",
    )


@pytest.mark.django_db
class TestPlanCRUD:
    def test_list_plans(self, user_client, plan):
        resp = user_client.get(f"{BASE_URL}/")
        assert resp.status_code == 200
        assert len(resp.data["results"]) >= 1

    def test_vendor_creates_plan(self, vendor_client, vendor):
        resp = vendor_client.post(
            f"{BASE_URL}/",
            {
                "name": "Starter Plan",
                "tier": "starter",
                "billing_cycle": "monthly",
                "price": 9900,
                "description": "스타터",
            },
        )
        assert resp.status_code == 201
        assert resp.data["vendor_name"] == vendor.company_name

    def test_user_cannot_create_plan(self, user_client):
        resp = user_client.post(
            f"{BASE_URL}/",
            {"name": "Hack", "tier": "starter", "billing_cycle": "monthly", "price": 100},
        )
        assert resp.status_code == 403

    def test_retrieve_plan(self, user_client, plan):
        resp = user_client.get(f"{BASE_URL}/{plan.pk}/")
        assert resp.status_code == 200
        assert resp.data["name"] == "Pro Plan"
