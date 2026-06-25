# Quickstart & Validation Guide

End-to-end validation scenarios for the Gurobi MCP Multi-User Backend. Proves the feature works
without restating implementation details (see [data-model.md](./data-model.md) and
[contracts/openapi.yaml](./contracts/openapi.yaml)).

## Prerequisites

- Ubuntu 24.04 host with Docker running and the `gurobi/mcp:latest` image pulled.
- Python 3.11+ with the project installed (`pip install -e .` plus dev extras).
- A **valid Gurobi Intelligence Access ID + Secret** for the integration scenarios (license-bound).
- Environment variables set:

  | Var | Purpose |
  |-----|---------|
  | `FERNET_KEY` | Symmetric key for encrypting Gurobi secrets at rest |
  | `JWT_SECRET` | Signing key for auth tokens |
  | `JWT_TTL` | Token lifetime (e.g. `3600`) |
  | `IDLE_TIMEOUT_MINUTES` | Idle reaper threshold (default `15`) |
  | `PORT_RANGE` | `61100-61200` |
  | `WORKSPACE_ROOT` | Base dir for per-user `/workspace` mounts |

## Run

```bash
# License-free tests (unit + REST contract) — default CI
pytest -m "not integration"

# Full round-trips (Docker + Gurobi license required)
pytest -m integration

# Start the service locally (loopback only)
uvicorn gurobimcp.main:app --host 127.0.0.1 --port 8000
```

## Scenario 1 — Register & sign in securely (US1)

1. `POST /auth/register` with username, password, Gurobi Access ID + Secret → `201`.
2. Inspect the SQLite DB directly: password is a bcrypt hash, the Gurobi secret is Fernet
   ciphertext — neither readable (SC-006). Grep logs: no secret/password/token appears (FR-005).
3. `POST /auth/login` with correct credentials → `200` with a JWT.
4. `POST /auth/login` with a wrong password → `401`, message does not reveal which factor failed.
5. Call any protected endpoint without the token → `401`.

**Pass when**: token round-trips, stored secrets are opaque, and unauthenticated calls are refused.

## Scenario 2 — Multi-turn conversation with agent binding (US2) `[integration]`

1. `POST /chat` `{conversation_id: c1, agent: explainer, message: ...}` → environment starts on a
   loopback port in 61100–61200; reply returned, `recovered: false`.
2. `POST /chat` `{conversation_id: c1, agent: explainer, message: <answer to its question>}` → reply
   reflects the earlier turn (not a restart).
3. `POST /chat` `{conversation_id: c1, agent: modeler, ...}` → `400` (agent-switch blocked, SC-009).
4. `POST /chat` `{conversation_id: c1, agent: bogus, ...}` → `400` before any agent is contacted.
5. `POST /chat` with `structured: true` (+ optional `schema`) → response includes a `structured`
   payload echoed from the agent unmodified (FR-016).
6. `POST /chat` with `input_files` that cause the agent to emit a file → `output_files` returned.

**Pass when**: continuity holds, binding is immutable, structured output and files pass through.

## Scenario 3 — Isolation & idle reaping (US3) `[integration]`

1. Drive activity for user A; confirm exactly one container `grbmcp-<A>` bound to 127.0.0.1.
2. As user B, attempt to reference A's conversation id → `403` (FR-025). Confirm B cannot reach A's
   port or workspace.
3. Leave A idle beyond `IDLE_TIMEOUT_MINUTES`; within one reaper cycle the container stops and its
   port is released (SC-004, SC-008).

**Pass when**: environments are isolated and idle ones are reclaimed with ports freed.

## Scenario 4 — Graceful recovery (US4) `[integration]`

1. Start conversation `c1`; force-stop A's container (simulating reaping).
2. `POST /chat` on `c1` again → a fresh environment starts, the turn is retried, response returns
   with `recovered: true` and no internal error surfaced (SC-003).

**Pass when**: the next message after reclamation succeeds and is flagged recovered.

## Scenario 5 — Capacity & exposure boundary

1. Exhaust the port pool (all 101 in use) and start one more environment → `503` capacity error.
2. From outside the host, probe the app port and any container port directly → all fail; only the
   Caddy HTTPS entry point responds (SC-007). Confirm `deploy/gurobimcp.service` restarts the app
   after a kill (SC-010).

**Pass when**: capacity is bounded, only the HTTPS entry point is reachable, and the service
self-restarts.
