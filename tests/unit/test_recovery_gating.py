"""Unit tests for ChatService recovery gating (US4). License-free.

Validates the rule ``recovered = environment was (re)provisioned this turn AND
the conversation already existed`` (FR-027/028) without Docker or MCP: a fake
backend reports whether it had to provision an environment, and the service
decides whether that counts as a transparent recovery.
"""

from __future__ import annotations

from gurobimcp.chat.registry import Registry
from gurobimcp.chat.service import AgentTurn, ChatService
from gurobimcp.models import User
from gurobimcp.schemas import ChatRequest


class ProvisionControlBackend:
    """Echoes the message; reports a caller-controlled ``provisioned`` flag."""

    def __init__(self) -> None:
        self.provisioned_next = False

    async def send_turn(
        self, user: User, agent: str, message: str, structured: bool, input_files: list
    ) -> AgentTurn:
        return AgentTurn(text=f"echo:{message}", provisioned=self.provisioned_next)

    async def stop(self, user_id: int) -> None:  # pragma: no cover - unused here
        return None

    async def reconcile(self) -> int:  # pragma: no cover - unused here
        return 0


def _user() -> User:
    return User(
        id=1,
        username="u",
        password_hash="x",
        grb_access_id="aid",
        grb_secret_enc="enc",
    )


def _req(message: str, conversation_id: str = "c1") -> ChatRequest:
    return ChatRequest(conversation_id=conversation_id, agent="gurobot", message=message)


async def test_first_message_cold_start_is_not_recovery() -> None:
    backend = ProvisionControlBackend()
    service = ChatService(Registry(), backend)
    backend.provisioned_next = True  # cold start provisions an env

    resp = await service.chat(_user(), _req("hello"))

    assert resp.text == "echo:hello"
    assert resp.recovered is False  # brand-new thread, not a recovery


async def test_reprovision_of_existing_thread_is_recovery() -> None:
    backend = ProvisionControlBackend()
    service = ChatService(Registry(), backend)
    user = _user()

    backend.provisioned_next = True
    await service.chat(user, _req("first"))  # thread now exists

    # Environment was reaped between turns → backend must provision again.
    backend.provisioned_next = True
    resp = await service.chat(user, _req("second"))

    assert resp.recovered is True  # active thread + reprovision (FR-027/028)


async def test_followup_on_live_environment_is_not_recovery() -> None:
    backend = ProvisionControlBackend()
    service = ChatService(Registry(), backend)
    user = _user()

    backend.provisioned_next = True
    await service.chat(user, _req("first"))

    backend.provisioned_next = False  # env still alive; no rebuild
    resp = await service.chat(user, _req("second"))

    assert resp.recovered is False


async def test_new_thread_on_live_environment_is_not_recovery() -> None:
    """A second conversation reusing a live env is fresh, not recovered."""
    backend = ProvisionControlBackend()
    service = ChatService(Registry(), backend)
    user = _user()

    backend.provisioned_next = True
    await service.chat(user, _req("first", conversation_id="c1"))

    backend.provisioned_next = False
    resp = await service.chat(user, _req("hello", conversation_id="c2"))

    assert resp.recovered is False
