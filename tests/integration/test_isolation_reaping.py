"""Integration: per-user isolation + idle reaping (T031).

Requires Docker, the gurobi/mcp image, and valid Intelligence Hub credentials in
``.env``. Skipped by default; run with ``pytest -m integration -s``.

Drives two real per-user environments and asserts US3 guarantees (FR-022/024/025/
026/033, SC-004/005):
  * two users get distinct loopback ports and distinct workspaces;
  * a conversation owned by user A is forbidden to user B (cross-user 403);
  * after the idle threshold, the reaper stops the idle environment and releases
    its port for reuse.
"""

from __future__ import annotations

import pathlib

import pytest

from gurobimcp.auth.security import encrypt_secret
from gurobimcp.chat.registry import Agent, ConversationForbidden, Registry
from gurobimcp.chat.service import ChatService, DockerMCPBackend
from gurobimcp.config import Settings
from gurobimcp.models import User
from gurobimcp.reaper import IdleReaper
from gurobimcp.schemas import ChatRequest

pytestmark = pytest.mark.integration


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = pathlib.Path(".env")
    if not p.exists():
        return env
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


_ENV = _load_env()
_HAVE_CREDS = bool(
    _ENV.get("GRB_INTELLIGENCE_ACCESS_ID") and _ENV.get("GRB_INTELLIGENCE_SECRET")
)


def _user(uid: int, settings: Settings) -> User:
    return User(
        id=uid,
        username=f"itest{uid}",
        password_hash="x",
        grb_access_id=_ENV["GRB_INTELLIGENCE_ACCESS_ID"],
        grb_secret_enc=encrypt_secret(_ENV["GRB_INTELLIGENCE_SECRET"], settings.fernet_key),
    )


def _purge(uid: int) -> None:
    try:
        import docker

        docker.from_env().containers.get(f"grbmcp-{uid}").remove(force=True)
    except Exception:
        pass


@pytest.mark.skipif(not _HAVE_CREDS, reason="requires Hub credentials in .env")
async def test_isolation_then_idle_reaping() -> None:
    # Reap aggressively: anything idle counts as idle this cycle.
    settings = Settings(idle_timeout_minutes=1)
    registry = Registry()
    backend = DockerMCPBackend(registry, settings)
    service = ChatService(registry, backend)
    reaper = IdleReaper(registry, backend, settings)

    user_a, user_b = _user(901, settings), _user(902, settings)
    for u in (user_a, user_b):
        _purge(u.id)

    try:
        # Bring up A's environment via a real turn.
        r_a = await service.chat(
            user_a,
            ChatRequest(conversation_id="iso-a", agent="gurobot", message="hello"),
        )
        assert r_a.text
        env_a = registry.environments[user_a.id]

        # Bring up B's environment; it must be a distinct port + workspace (FR-022/033).
        await service.chat(
            user_b,
            ChatRequest(conversation_id="iso-b", agent="gurobot", message="hello"),
        )
        env_b = registry.environments[user_b.id]
        assert env_a.port != env_b.port
        assert env_a.workspace_path != env_b.workspace_path

        # B cannot touch A's conversation (FR-025 / SC-005).
        with pytest.raises(ConversationForbidden):
            registry.bind_or_get("iso-a", user_b.id, Agent.GUROBOT)

        # Idle reaping: both envs are "idle" under the 1-min threshold once we
        # backdate them; the reaper stops them and frees their ports (FR-024/026).
        from datetime import UTC, datetime, timedelta

        old = datetime.now(UTC) - timedelta(minutes=5)
        env_a.last_used_at = old
        env_b.last_used_at = old
        free_before = backend._manager.pool.free_count  # noqa: SLF001

        reaped = await reaper.reap_once()

        assert set(reaped) == {user_a.id, user_b.id}
        assert user_a.id not in registry.environments
        assert backend._manager.pool.free_count == free_before + 2  # noqa: SLF001
    finally:
        for u in (user_a, user_b):
            await backend.stop(u.id)
            _purge(u.id)
