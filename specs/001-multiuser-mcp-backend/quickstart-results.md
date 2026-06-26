# Quickstart Validation Results (T044)

**Date**: 2026-06-26 · **Host**: Ubuntu (Azure), Docker running, `gurobi/mcp:latest` present,
valid Intelligence Hub credentials in `.env`.

Commands: `pytest` (license-free), `pytest -m integration` (real container + Hub round-trips),
`ruff check src tests`, `mypy`.

Summary: **50 license-free tests pass, 3 integration tests pass, ruff clean, mypy --strict clean.**

| Scenario | Status | Evidence |
|----------|--------|----------|
| 1 — Register & sign in securely (US1) | ✅ PASS | `tests/contract/test_auth.py` (201/409/200/401, missing-token), `tests/unit/test_security.py` (bcrypt/Fernet/JWT opaqueness + log scrubbing). |
| 2 — Multi-turn conversation & agent binding (US2) | ✅ PASS | `test_chat_roundtrip.py`: two turns on one conversation, the second reflects the first (continuity over the persistent MCP session); contract tests cover agent-switch→400, invalid-agent→400, structured passthrough, file I/O. |
| 3 — Isolation & idle reaping (US3) | ✅ PASS | `test_isolation_reaping.py`: two users get distinct loopback ports + workspaces, cross-user conversation → 403, reaper stops idle envs and frees their ports. |
| 4 — Graceful recovery (US4) | ✅ PASS | `test_recovery.py`: the idle reaper reclaims an active thread's environment, the next message cold-starts a fresh one and is flagged `recovered: true`, no internal error. |
| 5 — Capacity & exposure boundary | ⚠️ PARTIAL | Capacity→503 validated by `test_port_pool.py` (pool exhaustion → `CapacityError`) and `test_chat.py` (route surfaces 503/424). Loopback-only bind confirmed (`ss` shows `127.0.0.1:8000`). Full live port-exhaustion, external-port probing, and `systemd` auto-restart require a deployed host — see deploy artifacts below. |

## Notes / findings

- **Cold-start readiness (fixed during validation)**: `MCPSession.connect` now retries the MCP
  initialize handshake until the freshly-started container is serving, instead of racing the boot
  with a single attempt (was an intermittent `ConnectError`, most visible when starting a second
  container).
- **Per-session task ownership (fixed during validation)**: each container's MCP session now runs
  in its own dedicated task that owns the whole `async with` transport stack. The earlier design
  opened sessions on the main task and broke anyio's LIFO cancel-scope rule when the reaper closed
  one user's session while another stayed live (`RuntimeError: Attempted to exit a cancel scope…`).
  This was the blocker for multi-user isolation/reaping/recovery.
- **Recovery trigger**: the canonical US4 path is the idle reaper, which removes the environment
  from the registry; the next turn cold-starts fresh and is flagged recovered. A container that
  dies *while still registered* (external crash/force-kill) is a rarer edge whose stale call can
  wait on the MCP SSE read timeout before rebuilding — acceptable but slower; documented here.
- **Scenario 5 deployment items** are covered by `deploy/gurobimcp.service` (auto-start,
  `Restart=on-failure`) and `deploy/Caddyfile` (HTTPS, sole public entry point); these are validated
  by deploying to the host and opening only ports 80/443.
