import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

BASE_URL = "/api/v1/accounts"


@pytest.mark.django_db
class TestRegister:
    def test_register_user(self, api_client):
        resp = api_client.post(
            f"{BASE_URL}/register/",
            {"username": "newuser", "email": "new@test.com", "password": "securepass1", "role": "user"},
        )
        assert resp.status_code == 201
        assert resp.data["role"] == "user"

    def test_register_vendor(self, api_client):
        resp = api_client.post(
            f"{BASE_URL}/register/",
            {"username": "newvendor", "email": "v@test.com", "password": "securepass1", "role": "vendor"},
        )
        assert resp.status_code == 201
        assert resp.data["role"] == "vendor"

    def test_register_admin_blocked(self, api_client):
        resp = api_client.post(
            f"{BASE_URL}/register/",
            {"username": "hacker", "email": "h@test.com", "password": "securepass1", "role": "admin"},
        )
        assert resp.status_code == 400


@pytest.mark.django_db
class TestMe:
    def test_me_authenticated(self, user_client, normal_user):
        resp = user_client.get(f"{BASE_URL}/me/")
        assert resp.status_code == 200
        assert resp.data["username"] == normal_user.username

    def test_me_unauthenticated(self, api_client):
        resp = api_client.get(f"{BASE_URL}/me/")
        assert resp.status_code == 401


@pytest.mark.django_db
class TestToken:
    def test_obtain_token(self, api_client, normal_user):
        resp = api_client.post(
            f"{BASE_URL}/token/",
            {"username": normal_user.username, "password": "testpass123"},
        )
        assert resp.status_code == 200
        assert "access" in resp.data
        assert "refresh" in resp.data
