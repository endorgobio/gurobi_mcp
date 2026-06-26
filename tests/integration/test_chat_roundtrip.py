"""Integration: real round-trip against a gurobi/mcp container (T021).

Requires Docker, the gurobi/mcp image, and valid Intelligence Hub credentials
in ``.env`` (GRB_INTELLIGENCE_ACCESS_ID / GRB_INTELLIGENCE_SECRET). Skipped by
default; run with ``pytest -m integration -s``.

Drives the real ChatService + DockerMCPBackend through two turns on one
conversation (context continuity over the persistent MCP session) and then
probes whether the agents populate response-side ``structuredContent``.
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
async def test_two_turn_roundtrip_and_structured_probe() -> None:
    settings = Settings()  # reads .env (FERNET_KEY etc.)
    registry = Registry()
    backend = DockerMCPBackend(registry, settings)
    service = ChatService(registry, backend)

    user = User(
        id=999,
        username="itest",
        password_hash="x",
        grb_access_id=_ENV["GRB_INTELLIGENCE_ACCESS_ID"],
        grb_secret_enc=encrypt_secret(_ENV["GRB_INTELLIGENCE_SECRET"], settings.fernet_key),
    )

    # Best-effort: remove a leftover container from a prior run.
    try:
        import docker

        docker.from_env().containers.get(f"grbmcp-{user.id}").remove(force=True)
    except Exception:
        pass

    try:
        # Turn 1
        r1 = await service.chat(
            user,
            ChatRequest(
                conversation_id="it-1",
                agent="gurobot",
                message="In one short sentence, what is linear programming?",
            ),
        )
        print("\n[TURN 1] recovered=", r1.recovered)
        print("[TURN 1] text:", (r1.text or "")[:400])
        assert r1.text

        # Turn 2 — same conversation/agent; should reflect the first turn.
        r2 = await service.chat(
            user,
            ChatRequest(
                conversation_id="it-1",
                agent="gurobot",
                message="Give one concrete real-world example of that.",
            ),
        )
        print("\n[TURN 2] text:", (r2.text or "")[:400])
        assert r2.text

        # Structured-output probe — ask for JSON in the prompt, request structured.
        r3 = await service.chat(
            user,
            ChatRequest(
                conversation_id="it-structured",
                agent="gurobot",
                message='Reply ONLY with a JSON object of the form {"sum": <number>} '
                "for the value of 2+2. No prose.",
                structured=True,
            ),
        )
        print("\n[PROBE] text:", (r3.text or "")[:400])
        print("[PROBE] structuredContent:", r3.structured)
        print(
            "[PROBE] -> agents populate structuredContent?",
            "YES" if r3.structured else "NO (answer arrives in text only)",
        )
    finally:
        await backend.stop(user.id)
