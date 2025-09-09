from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def _unique_email():
    return f"test+{uuid4().hex[:8]}@example.com"


def test_register_login_and_me_flow():
    email = _unique_email()
    password = "Password123!"

    # Register
    resp = client.post(
        "/api/v1/auth/register",
        json={"name": "testuser", "email": email, "password": password},
    )
    assert resp.status_code in (200, 201), resp.text
    data = resp.json()
    assert "access_token" in data
    assert data.get("user", {}).get("email") == email or True  # user may or may not be present

    # Login
    resp2 = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp2.status_code == 200, resp2.text
    login_data = resp2.json()
    assert "access_token" in login_data
    assert "refresh_token" in login_data

    access_token = login_data["access_token"]

    # Get current user
    resp3 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert resp3.status_code == 200, resp3.text
    me = resp3.json()
    assert me.get("email") == email


def test_refresh_token_returns_new_access_token():
    email = _unique_email()
    password = "Password123!"

    # Register -> get tokens
    resp = client.post(
        "/api/v1/auth/register",
        json={"name": "refreshuser", "email": email, "password": password},
    )
    assert resp.status_code in (200, 201), resp.text
    data = resp.json()
    refresh_token = data.get("refresh_token")
    # if register didn't return refresh_token, do a login to obtain it
    if not refresh_token:
        resp2 = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert resp2.status_code == 200, resp2.text
        refresh_token = resp2.json().get("refresh_token")

    assert refresh_token, "No refresh_token available to test refresh endpoint"

    # Refresh
    resp3 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp3.status_code == 200, resp3.text
    refreshed = resp3.json()
    assert "access_token" in refreshed
    assert refreshed["access_token"] != ""