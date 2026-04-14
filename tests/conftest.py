import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.vendors.models import Vendor

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin1", password="testpass123", email="admin@test.com", role="admin"
    )


@pytest.fixture
def vendor_user(db):
    return User.objects.create_user(
        username="vendor1", password="testpass123", email="vendor@test.com", role="vendor"
    )


@pytest.fixture
def normal_user(db):
    return User.objects.create_user(
        username="user1", password="testpass123", email="user@test.com", role="user"
    )


@pytest.fixture
def vendor(vendor_user):
    return Vendor.objects.create(
        user=vendor_user,
        company_name="테스트 SaaS",
        business_number="123-45-67890",
        status="approved",
        commission_rate=10,
    )


@pytest.fixture
def admin_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.fixture
def vendor_client(api_client, vendor_user):
    api_client.force_authenticate(user=vendor_user)
    return api_client


@pytest.fixture
def user_client(api_client, normal_user):
    api_client.force_authenticate(user=normal_user)
    return api_client
