"""Contract tests for the auth endpoints (T011).

Covers register (201/409/400) and login (200/401) plus the protected-endpoint
guard. License-free: uses the in-memory DB fixture, no Docker/Hub access.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

_VALID = {
    "username": "alice",
    "password": "hunter2pw",
    "grb_access_id": "ACCESS123",
    "grb_secret": "topsecret",
}


def test_register_returns_201_and_public_user(client: TestClient) -> None:
    resp = client.post("/auth/register", json=_VALID)
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "alice"
    assert "id" in body
    # No secret material is ever returned.
    assert "password" not in body
    assert "grb_secret" not in body


def test_register_duplicate_username_returns_409(client: TestClient) -> None:
    assert client.post("/auth/register", json=_VALID).status_code == 201
    resp = client.post("/auth/register", json=_VALID)
    assert resp.status_code == 409


def test_register_missing_field_returns_422(client: TestClient) -> None:
    resp = client.post("/auth/register", json={"username": "bob"})
    assert resp.status_code == 422


def test_login_returns_token(client: TestClient) -> None:
    client.post("/auth/register", json=_VALID)
    resp = client.post(
        "/auth/login", json={"username": "alice", "password": "hunter2pw"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0


def test_login_wrong_password_returns_401(client: TestClient) -> None:
    client.post("/auth/register", json=_VALID)
    resp = client.post(
        "/auth/login", json={"username": "alice", "password": "nope"}
    )
    assert resp.status_code == 401


def test_login_unknown_user_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/auth/login", json={"username": "ghost", "password": "whatever"}
    )
    assert resp.status_code == 401


def test_protected_endpoint_requires_token(client: TestClient) -> None:
    resp = client.get("/auth/me")
    assert resp.status_code in (401, 403)


def test_protected_endpoint_accepts_valid_token(client: TestClient) -> None:
    client.post("/auth/register", json=_VALID)
    token = client.post(
        "/auth/login", json={"username": "alice", "password": "hunter2pw"}
    ).json()["access_token"]
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_protected_endpoint_rejects_garbage_token(client: TestClient) -> None:
    resp = client.get("/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert resp.status_code == 401
