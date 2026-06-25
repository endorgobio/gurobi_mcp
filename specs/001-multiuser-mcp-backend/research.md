# Phase 0 Research: Gurobi MCP Multi-User Backend

All Technical Context items were resolvable from the spec, the brief, the `gurobi/mcp`
documentation, and the constitution. No `NEEDS CLARIFICATION` markers remain. Decisions below.

## 1. Communicating with a `gurobi/mcp` container

- **Decision**: Manage each container with the Docker SDK for Python (`docker`), and talk to
  it through the official `mcp` Python SDK's `ClientSession` over the streamable-HTTP
  transport, connecting to the container's mapped loopback port.
- **Rationale**: The `gurobi/mcp` image is an MCP server exposing the three agents as tools on
  HTTP port `61095`. Using the `mcp` client SDK (initialize handshake → `list_tools` →
  `call_tool`) keeps us protocol-compliant (Constitution I) instead of hand-rolling HTTP.
  The Docker SDK gives programmatic run/stop/inspect without shelling out (avoids injection
  and parsing fragility).
- **Container invocation** (per user, on demand):
  - `image=gurobi/mcp:latest`
  - `ports={'61095/tcp': ('127.0.0.1', <allocated 61100–61200>)}` — loopback bind (FR-033)
  - `environment={GRB_INTELLIGENCE_ACCESS_ID, GRB_INTELLIGENCE_SECRET}` — decrypted per request
  - `volumes={<host per-user workspace>: {'bind': '/workspace', 'mode': 'rw'}}`
  - `name=grbmcp-<user_id>`, `detach=True`, plus a memory limit (`mem_limit`) to protect the 8 GB host
- **Readiness**: After `run`, poll the MCP `initialize` until it succeeds or a startup timeout
  elapses; on timeout, stop/remove the container and surface a clear error (FR-031, edge:
  "Environment fails to start").
- **Alternatives considered**: `aiodocker` (async-native) — rejected to avoid an extra dep; the
  `docker` SDK is sync and runs in a threadpool executor, which is sufficient at this scale.
  Raw `httpx` against the container — rejected: re-implements MCP framing, violates Principle I.

## 2. Persistent multi-turn MCP session & agent binding

- **Decision**: Hold one live `ClientSession` per running user environment in the in-memory
  registry, reused across turns for the life of the container. Each conversation is bound to one
  agent tool (`gurobot`/`explainer`/`modeler`) on first sight of its `conversation_id`; the
  binding and the owning user are stored with the session.
- **Rationale**: The explainer/modeler are multi-turn and track workflow state on the Gurobi
  side; a persistent session preserves that context (FR-013) and the binding prevents
  cross-agent state corruption (FR-010/012, Clarification).
- **Concurrency**: One `asyncio.Lock` per user environment serializes turns, satisfying
  "one active conversation per environment" (FR-029) and the concurrent-message edge case.
- **Alternatives considered**: New session per turn — rejected, breaks multi-turn agents.
  Stateless tool calls with client-side context replay — rejected, the agents own their state.

## 3. Idle reaping & graceful recovery

- **Decision**: A single asyncio background task (started in FastAPI lifespan) wakes on a fixed
  interval (e.g. 60 s), scans the registry, and stops any environment whose last-activity exceeds
  `IDLE_TIMEOUT_MINUTES` (default 15). Stopping closes the MCP session, stops/removes the
  container, releases the port, and drops the registry entry (FR-024/026). Each interaction
  updates last-activity under the user lock (FR-023).
- **Recovery**: On a turn for a conversation whose environment is gone, `chat.service` detects
  the stale entry, re-provisions the container + session, re-binds the same agent (fresh context),
  retries the turn once, and sets `recovered: true` in the response (FR-027/028, Story 4).
- **Rationale**: A timer loop is the simplest correct design (Principle V) and is robust to
  service restarts (registry is volatile by design; first post-restart message recovers — FR-030).
- **Alternatives considered**: Per-container timers — rejected (more moving parts). External cron
  — rejected (needs DB of state the app already holds in memory).

## 4. Credential safety

- **Decision**: Passwords hashed with bcrypt via `passlib`. Gurobi Secret encrypted at rest with
  Fernet (`cryptography`); the Fernet key is supplied via environment (`FERNET_KEY`) and never
  stored in the DB. Access ID stored plaintext (it is an identifier, not a secret) but treated as
  sensitive in logs. Auth tokens are JWTs signed with a server-side secret (`JWT_SECRET`),
  time-limited (`JWT_TTL`). A logging filter scrubs secret/token fields (FR-005).
- **Rationale**: Matches the brief's stated stack and the constitution's license-free testability
  (hashing/encryption are unit-testable without Gurobi).
- **Alternatives considered**: KMS/Vault for the Fernet key — out of scope for single-host v1
  (documented assumption); env-provided key is acceptable and keeps deployment simple.

## 5. Persistence boundary

- **Decision**: SQLite (via SQLAlchemy 2.0) stores only durable account data and last-known
  allocation hints. Live conversation/agent/session state lives in process memory and is
  intentionally lost on restart (spec assumption), with graceful recovery on next message.
- **Rationale**: Clean split between durable identity and volatile runtime; avoids a DB schema for
  transient session state. SQLite is sufficient for single-host v1.
- **Alternatives considered**: Postgres — unnecessary for single host. Persisting live sessions —
  rejected; sessions are tied to container lifetime which is itself volatile.

## 6. Port allocation

- **Decision**: An in-memory `PortPool` over 61100–61200 with allocate/release guarded by a lock;
  exhaustion raises a typed error mapped to a 503 "capacity reached" response (edge: pool
  exhaustion). On startup, reconcile by removing any orphaned `grbmcp-*` containers so ports start
  clean.
- **Rationale**: The range is the concurrency bound (SC-008); in-memory is fine since containers
  are volatile and reconciled at boot.

## 7. Deployment topology

- **Decision**: `uvicorn` bound to `127.0.0.1:8000`, run under a `systemd` unit
  (`deploy/gurobimcp.service`, auto-start + `Restart=on-failure` → FR-036/SC-010). `Caddy`
  (`deploy/Caddyfile`) terminates HTTPS on the public interface and reverse-proxies to
  `127.0.0.1:8000` as the sole external entry point (FR-032). Containers publish only to
  127.0.0.1, never the public NIC (FR-033, SC-007).
- **Rationale**: Directly realizes the spec's exposure boundary; Caddy gives automatic TLS.
- **Alternatives considered**: Nginx — viable but Caddy's auto-HTTPS is simpler; the brief names
  Caddy. Running uvicorn as the public listener — rejected, violates single-entry-point boundary.

## 8. Structured output (proxy mode)

- **Decision**: The `/chat` request carries `structured: bool` and optional `schema`. When set,
  the backend forwards them to the agent tool call and returns the agent's native structured
  content (MCP structured/`structuredContent` result) unmodified alongside any text; the backend
  does not define, validate, or coerce schemas of its own (Clarification 2026-06-25).
- **Rationale**: Keeps the backend a faithful proxy (Principle II — relay, don't reinterpret) and
  avoids inventing contracts the agents may not honor.
- **Open for planning→implementation**: exact MCP field carrying structured content is confirmed
  during the `[integration]` phase against the live image; the external REST contract is stable
  regardless (returned as a `structured` JSON field).

## 9. File exchange

- **Decision**: Input files are written into the user's mounted `/workspace` before the turn;
  output files produced by the agent under `/workspace` are returned as references (paths +
  metadata) in the response, with content retrievable via the workspace. Inline base64 is
  supported for small files. Final encoding confirmed in implementation; external behavior
  (files in → files out) is fixed (FR-017).
- **Rationale**: The image is built around a mounted `/workspace`; using it avoids a parallel
  transfer channel. Matches spec assumption on file transport.
