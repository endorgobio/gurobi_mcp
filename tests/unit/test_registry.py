"""Unit tests for conversation/agent binding rules (T019). License-free."""

from __future__ import annotations

import pytest

from gurobimcp.chat.registry import (
    Agent,
    AgentConflict,
    ConversationForbidden,
    ConversationNotFound,
    Registry,
)


def test_agent_enum_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        Agent("solver")


def test_first_sight_binds_agent() -> None:
    reg = Registry()
    conv = reg.bind_or_get("c1", user_id=1, agent=Agent.EXPLAINER)
    assert conv.agent is Agent.EXPLAINER
    assert conv.user_id == 1


def test_same_agent_followup_returns_same_conversation() -> None:
    reg = Registry()
    first = reg.bind_or_get("c1", 1, Agent.MODELER)
    again = reg.bind_or_get("c1", 1, Agent.MODELER)
    assert again is first


def test_agent_switch_is_rejected() -> None:
    reg = Registry()
    reg.bind_or_get("c1", 1, Agent.GUROBOT)
    with pytest.raises(AgentConflict):
        reg.bind_or_get("c1", 1, Agent.EXPLAINER)


def test_cross_user_access_is_forbidden() -> None:
    reg = Registry()
    reg.bind_or_get("c1", 1, Agent.GUROBOT)
    with pytest.raises(ConversationForbidden):
        reg.bind_or_get("c1", 2, Agent.GUROBOT)


def test_end_releases_binding_and_allows_rebind() -> None:
    reg = Registry()
    reg.bind_or_get("c1", 1, Agent.GUROBOT)
    reg.end("c1", 1)
    # After ending, the same id may bind a different agent.
    conv = reg.bind_or_get("c1", 1, Agent.MODELER)
    assert conv.agent is Agent.MODELER


def test_end_by_non_owner_is_forbidden() -> None:
    reg = Registry()
    reg.bind_or_get("c1", 1, Agent.GUROBOT)
    with pytest.raises(ConversationForbidden):
        reg.end("c1", 2)


def test_end_unknown_conversation_raises_not_found() -> None:
    reg = Registry()
    with pytest.raises(ConversationNotFound):
        reg.end("nope", 1)
