"""Contract tests for chat endpoints (T020).

License-free: the real Docker/MCP backend is replaced with a fake so binding,
validation, and error semantics are exercised without any container or Hub
access. The real path is covered by the [integration] test (T021).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from gurobimcp.chat.registry import Registry
from gurobimcp.chat.service import AgentTurn, ChatService
from gurobimcp.main import app
from gurobimcp.models import User
from gurobimcp.schemas import FileRef


class FakeBackend:
    """Echoes the message; records calls. No Docker, no MCP."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str]] = []

    async def send_turn(
        self,
        user: User,
        agent: str,
        message: str,
        structured: bool,
        input_files: list[FileRef],
    ) -> AgentTurn:
        self.calls.append((user.id, agent, message))
        return AgentTurn(
            text=f"[{agent}] echo: {message}",
            structured={"agent": agent, "echo": message} if structured else None,
            output_files=[FileRef(name="result.txt", path="/workspace/result.txt")]
            if input_files
            else [],
        )

    async def stop(self, user_id: int) -> None:  # pragma: no cover - not used here
        return None


@pytest.fixture()
def chat_client(client: TestClient) -> Iterator[TestClient]:
    """A client whose chat service uses the fake backend."""
    from gurobimcp.chat.service import get_chat_service

    service = ChatService(Registry(), FakeBackend())
    app.dependency_overrides[get_chat_service] = lambda: service
    yield client
    # base `client` fixture clears overrides on teardown


def _auth(client: TestClient, username: str = "alice") -> dict[str, str]:
    payload = {
        "username": username,
        "password": "hunter2pw",
        "grb_access_id": "AID",
        "grb_secret": "secret",
    }
    client.post("/auth/register", json=payload)
    token = client.post(
        "/auth/login", json={"username": username, "password": "hunter2pw"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_chat_requires_auth(chat_client: TestClient) -> None:
    resp = chat_client.post(
        "/chat", json={"conversation_id": "c1", "agent": "gurobot", "message": "hi"}
    )
    assert resp.status_code in (401, 403)


def test_chat_invalid_agent_returns_400(chat_client: TestClient) -> None:
    headers = _auth(chat_client)
    resp = chat_client.post(
        "/chat",
        json={"conversation_id": "c1", "agent": "solver", "message": "hi"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_chat_first_message_binds_and_replies(chat_client: TestClient) -> None:
    headers = _auth(chat_client)
    resp = chat_client.post(
        "/chat",
        json={"conversation_id": "c1", "agent": "explainer", "message": "explain"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent"] == "explainer"
    assert "explain" in body["text"]
    assert body["recovered"] is False


def test_chat_followup_same_agent_ok(chat_client: TestClient) -> None:
    headers = _auth(chat_client)
    base = {"conversation_id": "c1", "agent": "explainer"}
    chat_client.post("/chat", json={**base, "message": "first"}, headers=headers)
    resp = chat_client.post("/chat", json={**base, "message": "second"}, headers=headers)
    assert resp.status_code == 200


def test_chat_agent_switch_returns_400(chat_client: TestClient) -> None:
    headers = _auth(chat_client)
    chat_client.post(
        "/chat",
        json={"conversation_id": "c1", "agent": "explainer", "message": "first"},
        headers=headers,
    )
    resp = chat_client.post(
        "/chat",
        json={"conversation_id": "c1", "agent": "modeler", "message": "switch"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_chat_structured_output_passthrough(chat_client: TestClient) -> None:
    headers = _auth(chat_client)
    resp = chat_client.post(
        "/chat",
        json={
            "conversation_id": "c1",
            "agent": "modeler",
            "message": "model it",
            "structured": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["structured"] == {"agent": "modeler", "echo": "model it"}


def test_chat_cross_user_conversation_forbidden(chat_client: TestClient) -> None:
    alice = _auth(chat_client, "alice")
    chat_client.post(
        "/chat",
        json={"conversation_id": "shared", "agent": "gurobot", "message": "mine"},
        headers=alice,
    )
    bob = _auth(chat_client, "bob")
    resp = chat_client.post(
        "/chat",
        json={"conversation_id": "shared", "agent": "gurobot", "message": "intrude"},
        headers=bob,
    )
    assert resp.status_code == 403


def test_end_conversation_then_rebind(chat_client: TestClient) -> None:
    headers = _auth(chat_client)
    chat_client.post(
        "/chat",
        json={"conversation_id": "c1", "agent": "explainer", "message": "first"},
        headers=headers,
    )
    end = chat_client.post("/conversations/c1/end", headers=headers)
    assert end.status_code == 204
    # Same id may now bind a different agent.
    resp = chat_client.post(
        "/chat",
        json={"conversation_id": "c1", "agent": "modeler", "message": "fresh"},
        headers=headers,
    )
    assert resp.status_code == 200


def test_end_unknown_conversation_returns_404(chat_client: TestClient) -> None:
    headers = _auth(chat_client)
    resp = chat_client.post("/conversations/ghost/end", headers=headers)
    assert resp.status_code == 404
