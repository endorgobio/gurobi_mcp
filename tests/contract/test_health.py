"""Foundational smoke test: the app boots and the liveness probe responds.

Validates Phase 2 (lifespan, DB init, error handler, fixtures) end to end
without any Docker or Intelligence Hub access.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
