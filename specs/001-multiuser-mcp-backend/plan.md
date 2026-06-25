# Implementation Plan: Gurobi MCP Multi-User Backend

**Branch**: `001-multiuser-mcp-backend` | **Date**: 2026-06-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-multiuser-mcp-backend/spec.md`

## Summary

A headless JSON backend that lets many users each register with their own Gurobi Intelligence credentials, sign in for a token, and chat (multi-turn) with the three Gurobi agents — `gurobot`, `explainer`, `modeler`. On the first message of a conversation the backend starts an isolated per-user `gurobi/mcp` container (loopback-only port from 61100–61200, per-user workspace), opens a persistent MCP client session to it, binds the conversation to one agent, and proxies turns. A background reaper stops idle containers (default 15 min) and the next message transparently restarts and retries them (`recovered: true`). Structured output is supported in **proxy mode**: the request flag/schema is forwarded to the agent's native structured-output capability and the payload returned unmodified. Deployed as a systemd service behind a Caddy HTTPS reverse proxy; the app and all containers listen only on loopback.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FastAPI + Uvicorn (JSON API), `mcp` Python SDK (MCP client session to each container), Docker SDK for Python (`docker`) for container lifecycle, `passlib[bcrypt]` (password hashing), `cryptography` Fernet (secret encryption at rest), `PyJWT` (auth tokens), SQLAlchemy 2.0 (SQLite persistence), `pydantic`/`pydantic-settings` (models + config)

**Storage**: SQLite for durable user accounts (username, bcrypt hash, encrypted Gurobi credentials, last-activity, allocated port/container name). In-process memory for the live session/conversation registry (intentionally volatile per spec).

**Testing**: `pytest` + `pytest-asyncio`. Unit tests (security, port pool, agent-binding, reaper logic) and REST contract tests run license-free; full container/MCP round-trips marked `[integration]` and require Docker + a Gurobi license.

**Target Platform**: Linux server — Ubuntu Server 24.04 LTS on Azure (`Standard_B2as_v2`, 2 vCPU / 8 GB RAM), Docker 29.x, `gurobi/mcp` image present.

**Project Type**: Single-project web service (backend only; the chat web app is a separate, later project).

**Performance Goals**: First response (cold, includes container start) under 5 min (SC-001); warm follow-up reflects prior turn for ≥99% live-environment cases (SC-002); idle reclamation within one reaper cycle of the 15-min threshold (SC-004). No high-throughput target for v1 (single host).

**Constraints**: App and every container bound to 127.0.0.1 only; single HTTPS entry point via Caddy (FR-032/033). Bounded concurrency = 101 ports (61100–61200), one active conversation per environment (serialized). Secrets never logged (FR-005), never readable at rest (FR-003/004).

**Scale/Scope**: Up to ~100 concurrent active user environments bounded by the port pool and 8 GB RAM (realistic concurrency lower, limited by per-container memory). Single host; no horizontal scaling in v1.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

> **Scope note**: The constitution (v1.0.0) was authored for a Gurobi MCP **server that exposes solver tools**. This feature is a multi-user **backend/proxy** in front of the upstream `gurobi/mcp` containers — it is an MCP *client*, exposes a REST/JSON API (not MCP tools) to its own callers, and does not link `gurobipy`. Principles are applied in that adapted sense below. None of the adaptations are violations; they are scope clarifications.

| Principle | Status | How this plan complies |
|-----------|--------|------------------------|
| **I. MCP Protocol Compliance** | PASS (adapted) | Backend talks to each container through a compliant `mcp` SDK `ClientSession` (initialize handshake → tool discovery → typed `call_tool`), never ad-hoc HTTP against the container. The REST surface it exposes to the web app is documented contract-first in `contracts/openapi.yaml`. |
| **II. Optimization Correctness** | PASS (adapted) | Backend formulates no models; it MUST relay agent text, structured content, files, and any solver status/errors faithfully and never silently drop them (FR-016 proxy mode, FR-031 upstream errors surfaced). |
| **III. Test-First (NON-NEGOTIABLE)** | PASS | Tasks will be ordered test-first: failing unit/contract tests before implementation. Security, port-pool, agent-binding, and reaper logic are unit-tested without a license. |
| **IV. MCP Contract Testing** | PASS (adapted) | The external contract here is the REST API → license-free contract tests assert schemas, required fields, status codes, and error bodies. Container/MCP/solver round-trips are `[integration]` and excluded from the default run. |
| **V. Simplicity** | PASS | One FastAPI app, a handful of cohesive modules, no premature abstraction. Persistent MCP session + Docker lifecycle are intrinsic to the feature, not speculative. |

**Gate result (pre-Phase 0)**: PASS — no violations; Complexity Tracking left empty.

**Post-Phase 1 re-check**: PASS — design artifacts introduced no new complexity. Data model is two
durable+volatile tiers with one persisted entity; the REST contract is documented first
(`contracts/openapi.yaml`) honoring contract-first testing (IV); module layout stayed minimal (V).
No principle moved from PASS to fail; Complexity Tracking remains empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-multiuser-mcp-backend/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── openapi.yaml
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
src/
└── gurobimcp/
    ├── __init__.py
    ├── main.py            # FastAPI app, lifespan (DB init + reaper startup)
    ├── config.py          # Settings: idle timeout, port range, paths, keys (env-driven)
    ├── db.py              # SQLAlchemy engine/session for SQLite
    ├── models.py          # User ORM model
    ├── schemas.py         # Pydantic request/response models
    ├── auth/
    │   ├── security.py     # bcrypt hashing, Fernet encrypt/decrypt, JWT encode/decode
    │   ├── deps.py         # token → current user dependency
    │   └── routes.py       # POST /auth/register, POST /auth/login
    ├── containers/
    │   ├── port_pool.py    # allocate/release 61100–61200
    │   ├── manager.py      # Docker run/stop, per-user workspace, container naming
    │   └── mcp_client.py   # persistent MCP ClientSession per user, call_tool, structured output
    ├── chat/
    │   ├── registry.py     # in-memory session/conversation registry (agent binding, last-used)
    │   ├── service.py      # ensure-environment, bind agent, send turn, recovery/retry
    │   └── routes.py       # POST /chat, POST /conversations/{id}/end, GET /health
    └── reaper.py           # asyncio idle-reaper loop

tests/
├── contract/              # REST API contract tests (license-free)
├── integration/           # full Docker + MCP round-trips ([integration], needs license)
└── unit/                  # security, port_pool, registry/binding, reaper logic

deploy/
├── gurobimcp.service      # systemd unit
└── Caddyfile              # HTTPS reverse proxy → 127.0.0.1:8000
```

**Structure Decision**: Single-project backend web service. One installable package `gurobimcp` with cohesive modules grouped by concern (auth, containers, chat) plus a standalone reaper. Tests split into `unit/`, `contract/` (both license-free, default CI) and `integration/` (Docker + Gurobi license, opt-in) per Principle IV. `deploy/` holds the systemd unit and Caddyfile called out in the spec.

## Complexity Tracking

> No constitution violations — table intentionally empty.
