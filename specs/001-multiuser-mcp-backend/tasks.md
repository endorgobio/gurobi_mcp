---
description: "Task list for Gurobi MCP Multi-User Backend implementation"
---

# Tasks: Gurobi MCP Multi-User Backend

**Input**: Design documents from `/specs/001-multiuser-mcp-backend/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml

**Tests**: Test tasks are INCLUDED — the project constitution mandates Test-First development
(Principle III, NON-NEGOTIABLE) and contract testing (Principle IV). License-free unit/contract
tests run by default; container/MCP round-trips are marked `[integration]`.

**Organization**: Grouped by user story. US1 and US2 are both P1; US1 is the smallest standalone
slice, US2 is the core product value. MVP = US1 + US2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US4; omitted for Setup/Foundational/Polish
- All paths are repository-relative

## Path Conventions

Single-project backend: package at `src/gurobimcp/`, tests at `tests/`, deployment at `deploy/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton and toolchain

- [X] T001 Create directory structure (`src/gurobimcp/{auth,containers,chat}/`, `tests/{unit,contract,integration}/`, `deploy/`) per plan.md
- [X] T002 Initialize Python project in `pyproject.toml` with deps: fastapi, uvicorn, mcp, docker, passlib[bcrypt], cryptography, PyJWT, SQLAlchemy, pydantic, pydantic-settings, pytest, pytest-asyncio
- [X] T003 [P] Configure ruff and mypy (strict mode) in `pyproject.toml` per constitution Technology Stack
- [X] T004 [P] Configure pytest in `pyproject.toml` with an `integration` marker and async mode

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure required before ANY user story

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T005 Implement settings in `src/gurobimcp/config.py` (env: FERNET_KEY, JWT_SECRET, JWT_TTL, IDLE_TIMEOUT_MINUTES, PORT_RANGE=61100-61200, WORKSPACE_ROOT)
- [X] T006 [P] Implement SQLite engine + session factory in `src/gurobimcp/db.py`
- [X] T007 [P] Implement secret-scrubbing logging filter + structured error handling in `src/gurobimcp/logging.py` (FR-005)
- [X] T008 Create FastAPI app + lifespan stub + `GET /health` in `src/gurobimcp/main.py`
- [X] T009 [P] Shared pytest fixtures (TestClient, temp SQLite DB) in `tests/conftest.py`

**Checkpoint**: App boots, `/health` responds, DB initializes, secrets are scrubbed from logs

---

## Phase 3: User Story 1 - Register and sign in securely (Priority: P1) 🎯 MVP

**Goal**: Secure accounts — register with Gurobi credentials, sign in for a token, protect endpoints.

**Independent Test**: Register an account, log in to get a JWT, hit a protected endpoint with/without it, and confirm stored password/secret are opaque in the DB and absent from logs.

### Tests for User Story 1 ⚠️ (write first, must FAIL before implementation)

- [X] T010 [P] [US1] Unit tests for bcrypt hashing, Fernet encrypt/decrypt, JWT encode/decode in `tests/unit/test_security.py`
- [X] T011 [P] [US1] Contract tests for `POST /auth/register` and `POST /auth/login` (201/400/409/200/401) in `tests/contract/test_auth.py`

### Implementation for User Story 1

- [X] T012 [P] [US1] `User` ORM model in `src/gurobimcp/models.py` (unique username, password_hash, grb_access_id, grb_secret_enc, last_active_at, allocated_port, container_name, created_at)
- [X] T013 [P] [US1] Auth Pydantic schemas (RegisterRequest, LoginRequest, TokenResponse, UserPublic) in `src/gurobimcp/schemas.py`
- [X] T014 [US1] Security helpers (hash/verify password, Fernet encrypt/decrypt secret, JWT issue/verify) in `src/gurobimcp/auth/security.py`
- [X] T015 [US1] Current-user dependency (Bearer token → User, 401 on missing/expired) in `src/gurobimcp/auth/deps.py` (depends on T014)
- [X] T016 [US1] Auth routes register (409 on duplicate, FR-002) + login (401 generic, FR-006) in `src/gurobimcp/auth/routes.py` (depends on T012–T015)
- [X] T017 [US1] Wire auth router into `src/gurobimcp/main.py` and apply auth guard to protected routes

**Checkpoint**: US1 fully functional and independently testable

---

## Phase 4: User Story 2 - Multi-turn conversation with agent binding (Priority: P1)

**Goal**: Chat multi-turn with one bound agent; per-user container started on demand; structured output (proxy mode) and files pass through.

**Independent Test**: From an authenticated session, start a thread bound to one agent, send a follow-up that reflects the earlier turn, confirm agent-switch and invalid-agent are rejected, and confirm a structured-output request returns a structured payload.

### Tests for User Story 2 ⚠️ (write first, must FAIL before implementation)

- [X] T018 [P] [US2] Unit tests for `PortPool` allocate/release/exhaustion in `tests/unit/test_port_pool.py`
- [X] T019 [P] [US2] Unit tests for conversation/agent binding rules (first-sight bind, switch rejection, invalid agent) in `tests/unit/test_registry.py`
- [X] T020 [P] [US2] Contract tests for `POST /chat` and `POST /conversations/{id}/end` (200/400/401/403) in `tests/contract/test_chat.py`
- [X] T021 [P] [US2] Integration test: two-turn round-trip preserves context `[integration]` in `tests/integration/test_chat_roundtrip.py`

### Implementation for User Story 2

- [X] T022 [P] [US2] `PortPool` over 61100–61200 with lock + CapacityError in `src/gurobimcp/containers/port_pool.py`
- [X] T023 [P] [US2] In-memory registry (UserEnvironment, Conversation, agent binding, last_used) in `src/gurobimcp/chat/registry.py`
- [X] T024 [P] [US2] Chat schemas (ChatRequest, ChatResponse, FileRef) in `src/gurobimcp/schemas.py`
- [X] T025 [US2] Container manager: Docker run (loopback bind, env creds, workspace mount, mem_limit), stop/remove, readiness poll in `src/gurobimcp/containers/manager.py` (depends on T022)
- [X] T026 [US2] MCP client wrapper: persistent ClientSession, initialize, `call_tool` per agent, structured-output forwarding in `src/gurobimcp/containers/mcp_client.py` (depends on T025)
- [X] T027 [US2] Chat service: ensure-environment, bind/validate agent, send turn, structured output (proxy mode FR-016), file I/O via workspace, per-user lock serialization (FR-029) in `src/gurobimcp/chat/service.py` (depends on T023, T026)
- [X] T028 [US2] Chat routes `POST /chat` + `POST /conversations/{id}/end` (FR-011/012/018, 403 cross-user FR-025) in `src/gurobimcp/chat/routes.py` (depends on T024, T027)
- [X] T029 [US2] Wire chat router into `src/gurobimcp/main.py`

**Checkpoint**: US1 + US2 work independently — this is the demoable MVP

---

## Phase 5: User Story 3 - Isolation and automatic resource reclamation (Priority: P2)

**Goal**: Per-user isolation enforced; idle environments reaped and ports freed; activity resets the timer.

**Independent Test**: Drive one account to a running container, confirm a second account cannot reach its port/workspace/conversation, leave it idle past the threshold, and confirm it is stopped and its port released.

### Tests for User Story 3 ⚠️ (write first, must FAIL before implementation)

- [X] T030 [P] [US3] Unit tests for reaper idle-selection and port-release logic in `tests/unit/test_reaper.py`
- [X] T031 [P] [US3] Integration test: isolation between two users + idle reaping `[integration]` in `tests/integration/test_isolation_reaping.py`

### Implementation for User Story 3

- [X] T032 [US3] Idle-reaper asyncio loop (scan registry, stop environments idle > IDLE_TIMEOUT_MINUTES, close session, release port) in `src/gurobimcp/reaper.py` (depends on T023, T025)
- [X] T033 [US3] Update `last_used_at` on each turn under the user lock in `src/gurobimcp/chat/service.py` (FR-023)
- [X] T034 [US3] Per-user workspace isolation + assert loopback-only publish in `src/gurobimcp/containers/manager.py` (FR-022/033)
- [X] T035 [US3] Start reaper in lifespan + boot-time reconciliation (remove orphan `grbmcp-*`, reset pool) in `src/gurobimcp/main.py` (depends on T032)

**Checkpoint**: US1–US3 independently functional; resources reclaimed safely

---

## Phase 6: User Story 4 - Graceful recovery after reclamation (Priority: P3)

**Goal**: A message to a thread whose environment was reaped transparently restarts it, retries, and flags `recovered: true`.

**Independent Test**: Start a thread, force-stop its container, send another message on the same thread, and confirm a valid response with `recovered: true` and no internal error.

### Tests for User Story 4 ⚠️ (write first, must FAIL before implementation)

- [X] T036 [P] [US4] Integration test: recovery after forced reclamation returns `recovered: true` `[integration]` in `tests/integration/test_recovery.py`

### Implementation for User Story 4

- [X] T037 [US4] Stale-environment detection + re-provision + single retry + set `recovered=true` in `src/gurobimcp/chat/service.py` (FR-027/028, depends on T027)
- [X] T038 [US4] First-message-after-restart recovery using volatile registry + clear upstream/start-failure errors (FR-030/031) in `src/gurobimcp/chat/service.py`

**Checkpoint**: All four user stories independently functional

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Deployment, hardening, and end-to-end validation

- [X] T039 [P] systemd unit (auto-start, Restart=on-failure) in `deploy/gurobimcp.service` (FR-036/SC-010)
- [X] T040 [P] Caddy reverse proxy (HTTPS → 127.0.0.1:8000 as sole entry point) in `deploy/Caddyfile` (FR-032/SC-007)
- [X] T041 [P] README with env vars, install, run, and deploy steps in `README.md`
- [X] T042 Map capacity exhaustion → 503 and upstream-credential/start failure → 424 across chat routes (edge cases, FR-031)
- [X] T043 [P] mypy --strict and ruff clean pass across `src/gurobimcp/`
- [X] T044 Execute `quickstart.md` validation scenarios 1–5 and record results

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: depends on Foundational
- **US2 (Phase 4)**: depends on Foundational; independent of US1 (different modules), though both ship for MVP
- **US3 (Phase 5)**: depends on Foundational + US2's container/registry layer (T023, T025)
- **US4 (Phase 6)**: depends on US2's chat service (T027); conceptually hardens US3
- **Polish (Phase 7)**: depends on the desired stories being complete

### User Story Dependencies

- **US1 (P1)**: standalone after Foundational
- **US2 (P1)**: standalone after Foundational
- **US3 (P2)**: builds on US2 runtime (container manager + registry)
- **US4 (P3)**: builds on US2 chat service

### Within Each User Story

- Tests written and failing before implementation (Principle III)
- Models/schemas before services; services before routes; routes before wiring
- Story complete before moving to the next priority

### Parallel Opportunities

- Setup: T003, T004 in parallel
- Foundational: T006, T007, T009 in parallel (after T005)
- US1: T010, T011 (tests) in parallel; then T012, T013 (model + schemas) in parallel
- US2: T018–T021 (tests) in parallel; then T022, T023, T024 in parallel
- US3: T030, T031 (tests) in parallel
- Polish: T039, T040, T041, T043 in parallel
- After Foundational, US1 and US2 can be built by different developers concurrently

---

## Parallel Example: User Story 2

```bash
# Tests first (must fail):
Task: "Unit tests for PortPool in tests/unit/test_port_pool.py"
Task: "Unit tests for agent binding in tests/unit/test_registry.py"
Task: "Contract tests for /chat in tests/contract/test_chat.py"
Task: "Integration test two-turn round-trip in tests/integration/test_chat_roundtrip.py"

# Then independent building blocks together:
Task: "PortPool in src/gurobimcp/containers/port_pool.py"
Task: "In-memory registry in src/gurobimcp/chat/registry.py"
Task: "Chat schemas in src/gurobimcp/schemas.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2)

1. Phase 1: Setup
2. Phase 2: Foundational (CRITICAL — blocks all stories)
3. Phase 3: US1 → validate secure auth independently
4. Phase 4: US2 → validate multi-turn chat independently
5. **STOP and VALIDATE**: this is the demoable MVP (register → sign in → chat with an agent)

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. US1 → secure accounts (deploy/demo)
3. US2 → core chat (deploy/demo — MVP)
4. US3 → isolation + idle reaping (deploy/demo)
5. US4 → graceful recovery (deploy/demo)
6. Polish → deployment units + quickstart validation

### Parallel Team Strategy

After Foundational: Developer A → US1, Developer B → US2; once US2 lands, US3 and US4 follow on its runtime.

---

## Notes

- `[P]` = different files, no dependencies on incomplete tasks
- `[integration]` tests require Docker + Intelligence Hub credentials and are excluded from the default `pytest` run
- Tests MUST fail before implementing (Principle III, NON-NEGOTIABLE)
- Commit after each task or logical group, referencing the task ID
- Secrets/passwords/tokens never logged or returned (FR-003/004/005) — verify in T007, T010, T044
- Stop at any checkpoint to validate a story independently
