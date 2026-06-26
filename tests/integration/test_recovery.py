"""Integration: graceful recovery after forced reclamation (T036).

Requires Docker, the gurobi/mcp image, and valid Intelligence Hub credentials in
``.env``. Skipped by default; run with ``pytest -m integration -s``.

Scenario (US4 / FR-027/028): start a thread, force-stop its container behind the
backend's back, then send another message on the same conversation. The backend
must detect the stale session, rebuild the environment, retry the turn, and
return a valid response flagged ``recovered: true`` — never an internal error.
"""

from __future__ import annotations

import pathlib

import pytest

from gurobimcp.auth.security import encrypt_secret
from gurobimcp.chat.registry import Registry
from gurobimcp.chat.service import ChatService, DockerMCPBackend
from gurobimcp.config import Settings
from gurobimcp.models import User
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


@pytest.mark.skipif(not _HAVE_CREDS, reason="requires Hub credentials in .env")
async def test_recovery_after_forced_reclamation() -> None:
    settings = Settings()
    registry = Registry()
    backend = DockerMCPBackend(registry, settings)
    service = ChatService(registry, backend)

    user = User(
        id=903,
        username="itest-recover",
        password_hash="x",
        grb_access_id=_ENV["GRB_INTELLIGENCE_ACCESS_ID"],
        grb_secret_enc=encrypt_secret(_ENV["GRB_INTELLIGENCE_SECRET"], settings.fernet_key),
    )

    try:
        import docker

        docker.from_env().containers.get(f"grbmcp-{user.id}").remove(force=True)
    except Exception:
        pass

    try:
        # Turn 1 — cold start; not a recovery.
        r1 = await service.chat(
            user,
            ChatRequest(conversation_id="rec-1", agent="gurobot", message="Say hello."),
        )
        assert r1.text
        assert r1.recovered is False

        # Force-stop the container behind the backend's back: the registry still
        # holds the (now-dead) environment, so the next call must detect staleness.
        import docker

        docker.from_env().containers.get(f"grbmcp-{user.id}").remove(force=True)

        # Turn 2 — same thread; transparent recovery expected.
        r2 = await service.chat(
            user,
            ChatRequest(
                conversation_id="rec-1",
                agent="gurobot",
                message="Are you still there? Reply in one sentence.",
            ),
        )
        print("\n[RECOVERY] recovered=", r2.recovered)
        print("[RECOVERY] text:", (r2.text or "")[:300])
        assert r2.text  # valid response, not an internal error (FR-027)
        assert r2.recovered is True  # flagged as recovered (FR-028)
    finally:
        await backend.stop(user.id)
        try:
            import docker

            docker.from_env().containers.get(f"grbmcp-{user.id}").remove(force=True)
        except Exception:
            pass
