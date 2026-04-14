import pytest

from apps.vendors.models import Vendor

BASE_URL = "/api/v1/vendors"


@pytest.mark.django_db
class TestVendorRegister:
    def test_vendor_register(self, vendor_client):
        resp = vendor_client.post(
            f"{BASE_URL}/register/",
            {"company_name": "My SaaS", "business_number": "111-22-33333"},
        )
        assert resp.status_code == 201
        assert resp.data["status"] == "pending"

    def test_user_cannot_register_vendor(self, user_client):
        resp = user_client.post(
            f"{BASE_URL}/register/",
            {"company_name": "Nope", "business_number": "000-00-00000"},
        )
        assert resp.status_code == 403


@pytest.mark.django_db
class TestVendorApproval:
    def test_admin_approves_vendor(self, admin_client, vendor):
        resp = admin_client.patch(
            f"{BASE_URL}/{vendor.pk}/approve/",
            {"status": "approved", "commission_rate": "15.00"},
        )
        assert resp.status_code == 200
        vendor.refresh_from_db()
        assert vendor.status == "approved"

    def test_vendor_cannot_approve(self, vendor_client, vendor):
        resp = vendor_client.patch(
            f"{BASE_URL}/{vendor.pk}/approve/",
            {"status": "approved"},
        )
        assert resp.status_code == 403


@pytest.mark.django_db
class TestVendorList:
    def test_list_vendors(self, user_client, vendor):
        resp = user_client.get(f"{BASE_URL}/")
        assert resp.status_code == 200
        assert len(resp.data["results"]) >= 1
