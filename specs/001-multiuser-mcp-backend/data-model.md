# Phase 1 Data Model: Gurobi MCP Multi-User Backend

Two tiers: **durable** (SQLite) and **volatile** (in-process registry). Field types are logical;
exact column/Pydantic types are settled in implementation.

## Durable entities (SQLite)

### User

The only persisted entity.

| Field | Type | Notes |
|-------|------|-------|
| `id` | int (PK) | Surrogate key. |
| `username` | str, unique, not null | Login identifier; uniqueness enforced (FR-002). |
| `password_hash` | str, not null | bcrypt hash; never reversible/returned (FR-003). |
| `grb_access_id` | str, not null | Gurobi Intelligence Access ID (identifier; sensitive in logs). |
| `grb_secret_enc` | bytes/str, not null | Fernet-encrypted Gurobi Secret (FR-004); never returned. |
| `last_active_at` | datetime, nullable | Updated on each interaction (FR-023); also informs reaping. |
| `allocated_port` | int, nullable | Last allocated loopback port (hint; authoritative state is in-memory). |
| `container_name` | str, nullable | `grbmcp-<id>` when running (hint; reconciled at boot). |
| `created_at` | datetime, not null | Account creation time. |

**Validation rules**
- `username` unique → duplicate registration rejected (FR-002).
- `password_hash`, `grb_secret_enc` MUST be non-plaintext (FR-003/004); enforced in `auth.security`.
- No field is ever logged in readable form (FR-005).

**State**: an account has no lifecycle states in v1 (no disable/delete — out of scope).

## Volatile entities (in-process registry, lost on restart by design)

### UserEnvironment

One per running container; keyed by `user_id`.

| Field | Type | Notes |
|-------|------|-------|
| `user_id` | int | Owner. |
| `container_id` | str | Docker container id. |
| `port` | int | Allocated 61100–61200 port (loopback). |
| `workspace_path` | str | Host dir mounted at `/workspace`. |
| `mcp_session` | object | Live MCP `ClientSession` (persistent across turns). |
| `lock` | asyncio.Lock | Serializes turns (FR-029). |
| `last_used_at` | datetime | Drives idle reaping (FR-024). |
| `state` | enum | `starting` \| `ready` \| `stopping`. |

**Lifecycle**: `starting` → `ready` (after MCP initialize) → reaped/stopped → entry removed and
port released (FR-026). Stale entry on next turn triggers recovery (FR-027).

### Conversation

Tracks agent binding and context ownership; keyed by `conversation_id`.

| Field | Type | Notes |
|-------|------|-------|
| `conversation_id` | str | Caller-supplied identifier (FR-009). |
| `user_id` | int | Owner; cross-user access rejected (FR-025). |
| `agent` | enum | `gurobot` \| `explainer` \| `modeler`; bound on first sight, immutable (FR-010/012). |
| `created_at` | datetime | First-seen time. |
| `active` | bool | False after explicit end (FR-018). |

**Validation / transitions**
- First sight of a `conversation_id` for a user binds `agent` and begins fresh context (FR-014).
- Follow-up with a different `agent` for an existing conversation → reject, binding unchanged
  (FR-012).
- Invalid/missing `agent` on any chat request → reject before contacting any agent (FR-011).
- Explicit end → `active=false`, retained context released (FR-018); a new id may bind any agent.
- Context is tied to the environment's life: if the environment is reaped, in-progress context is
  gone and the next turn recovers with fresh context (FR-026/027).

### PortPool

Singleton managing the 61100–61200 range.

| Field | Type | Notes |
|-------|------|-------|
| `available` | set[int] | Free ports. |
| `in_use` | dict[int, user_id] | Allocations. |

**Rules**: allocate/release under a lock; empty `available` → typed `CapacityError` → 503
(SC-008, pool-exhaustion edge).

## Derived / non-stored

- **Authorization token**: a JWT carrying `sub=user_id` and an expiry; signed server-side, never
  stored. Verified per protected request (FR-006/007).
- **Message turn**: a request/response pair (text and/or structured payload, optional input/output
  files, `recovered` flag). Transient; not persisted in v1.

## Relationships

```
User (1) ──< Conversation (N)        [by user_id]
User (1) ──  UserEnvironment (0..1)  [one active container per user]
UserEnvironment (1) ── PortPool slot (1)
Conversation (N) ── UserEnvironment (1)   [context lives in the user's environment]
```
