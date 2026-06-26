"""In-memory conversation/environment registry (T023).

Volatile by design (FR/assumptions): live state is held in process memory and
lost on restart, with graceful recovery on the next message (US4). This module
is pure data + binding logic — no Docker, no MCP — so it is fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Agent(StrEnum):
    """The three supported agents; ``Agent(value)`` raises ValueError if unknown."""

    GUROBOT = "gurobot"
    EXPLAINER = "explainer"
    MODELER = "modeler"


class RegistryError(Exception):
    """Base class for registry binding errors."""


class AgentConflict(RegistryError):
    """A follow-up named a different agent than the one bound (FR-012)."""


class ConversationForbidden(RegistryError):
    """A conversation is owned by a different user (FR-025)."""


class ConversationNotFound(RegistryError):
    """No such conversation for this user (FR-018 end of unknown id)."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Conversation:
    conversation_id: str
    user_id: int
    agent: Agent
    created_at: datetime = field(default_factory=_utcnow)
    active: bool = True


@dataclass
class UserEnvironment:
    """Metadata for a running per-user container (populated by the backend)."""

    user_id: int
    container_id: str
    port: int
    workspace_path: str
    session: Any = None  # live MCP ClientSession (opaque to the registry)
    state: str = "ready"
    last_used_at: datetime = field(default_factory=_utcnow)


class Registry:
    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self.environments: dict[int, UserEnvironment] = {}

    # --- Conversation binding (FR-010/012/014/025) ---

    def bind_or_get(self, conversation_id: str, user_id: int, agent: Agent) -> Conversation:
        existing = self._conversations.get(conversation_id)
        if existing is None or not existing.active:
            conv = Conversation(conversation_id=conversation_id, user_id=user_id, agent=agent)
            self._conversations[conversation_id] = conv
            return conv
        if existing.user_id != user_id:
            raise ConversationForbidden(conversation_id)
        if existing.agent is not agent:
            raise AgentConflict(
                f"Conversation '{conversation_id}' is bound to '{existing.agent.value}'"
            )
        return existing

    def has_active_conversation(self, conversation_id: str, user_id: int) -> bool:
        """True if this user already owns an active thread with this id (US4).

        Used to tell a genuine first message apart from a follow-up whose
        environment was reclaimed: only the latter counts as a recovery.
        """
        existing = self._conversations.get(conversation_id)
        return existing is not None and existing.active and existing.user_id == user_id

    def end(self, conversation_id: str, user_id: int) -> None:
        existing = self._conversations.get(conversation_id)
        if existing is None or not existing.active:
            raise ConversationNotFound(conversation_id)
        if existing.user_id != user_id:
            raise ConversationForbidden(conversation_id)
        del self._conversations[conversation_id]

    # --- Environment bookkeeping + activity (FR-023) ---

    def touch(self, user_id: int) -> None:
        env = self.environments.get(user_id)
        if env is not None:
            env.last_used_at = _utcnow()
