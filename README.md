# Gurobi MCP Multi-User Backend

A FastAPI backend that lets multiple users each run their own isolated
`gurobi/mcp` container against their own Gurobi Intelligence Hub credentials, and
chat multi-turn with the three Hub agents — `gurobot`, `explainer`, `modeler`.

This service is a **proxy**: it builds and solves no optimization models itself
and links no `gurobipy`. On the first message of a conversation it starts a
per-user container (loopback-only, on a port from 61100–61200, with a private
workspace), opens a persistent MCP session, binds the conversation to one agent,
and relays turns. An idle reaper stops unused containers and the next message
transparently restarts them (`recovered: true`).

See [specs/001-multiuser-mcp-backend/](specs/001-multiuser-mcp-backend/) for the
spec, plan, tasks, and the REST contract
([openapi.yaml](specs/001-multiuser-mcp-backend/contracts/openapi.yaml)).

## Architecture at a glance

```
client ──HTTPS──> Caddy (:443) ──> FastAPI app (127.0.0.1:8000)
                                         │  one per user, on demand
                                         ├─> gurobi/mcp container (127.0.0.1:61100)
                                         ├─> gurobi/mcp container (127.0.0.1:61101)
                                         └─> ...
```

The app and every container bind to `127.0.0.1` only (FR-033); Caddy is the sole
public entry point (FR-032).

## Requirements

- Linux host (Ubuntu 24.04) with **Docker** running and the `gurobi/mcp:latest`
  image pulled (`docker pull gurobi/mcp:latest`).
- **Python 3.11+**.
- **Gurobi Intelligence Hub credentials** (Access ID + Secret) — required only to
  actually chat (the integration tests); unit/contract tests need none.

## Configuration

All settings are environment-driven (see [src/gurobimcp/config.py](src/gurobimcp/config.py)).
Defaults are dev-friendly; **`FERNET_KEY` and `JWT_SECRET` must be set** for any
real deployment.

| Variable | Default | Purpose |
|----------|---------|---------|
| `FERNET_KEY` | _(empty)_ | Fernet key encrypting each user's Gurobi secret at rest (FR-004). Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `JWT_SECRET` | _(empty)_ | HMAC secret signing auth tokens (FR-006). Use ≥32 random bytes. |
| `JWT_TTL` | `3600` | Auth-token lifetime, seconds. |
| `IDLE_TIMEOUT_MINUTES` | `15` | Stop environments idle longer than this (FR-024/035). |
| `REAPER_INTERVAL_SECONDS` | `60` | How often the idle reaper scans. |
| `PORT_RANGE` | `61100-61200` | Inclusive loopback port pool (FR-021); bounds concurrency. |
| `WORKSPACE_ROOT` | `./workspaces` | Base dir for per-user `/workspace` mounts (FR-022). |
| `DATABASE_URL` | `sqlite:///./gurobimcp.db` | Durable user store. |
| `MCP_IMAGE` | `gurobi/mcp:latest` | Container image started per user. |
| `CONTAINER_MEM_LIMIT` | `1g` | Per-container memory cap. |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | App bind address (keep loopback). |

Provide them via the environment or a `.env` file in the working directory.

## Install

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

(Equivalently, `python -m venv .venv && .venv/bin/pip install -e ".[dev]"`.)

## Run

```bash
# License-free tests (unit + REST contract) — the default CI run
.venv/bin/pytest

# Full container/MCP round-trips (Docker + Hub credentials in .env required)
.venv/bin/pytest -m integration -s

# Lint + type-check (strict)
.venv/bin/ruff check src tests
.venv/bin/mypy

# Start the service locally (loopback only)
.venv/bin/uvicorn gurobimcp.main:app --host 127.0.0.1 --port 8000
```

With the server running and `GRB_INTELLIGENCE_ACCESS_ID` / `GRB_INTELLIGENCE_SECRET`
in `.env`, drive a full sign-up → login → chat round-trip:

```bash
./scripts/smoke_e2e.sh
```

## API

| Method & path | Purpose |
|---------------|---------|
| `POST /auth/register` | Create an account with username, password, and Gurobi credentials → `201` (`409` if the username exists). |
| `POST /auth/login` | Exchange credentials for a JWT → `200` (`401` on bad credentials). |
| `POST /chat` | Send a turn to a conversation's bound agent → `200`. `400` invalid/switched agent, `403` cross-user, `424` environment/upstream failure, `503` capacity reached. |
| `POST /conversations/{id}/end` | Release a conversation's context → `204` (`404` unknown). |
| `GET /health` | Liveness probe. |

Protected routes require `Authorization: Bearer <token>`. Full schemas:
[contracts/openapi.yaml](specs/001-multiuser-mcp-backend/contracts/openapi.yaml).

## Deploy

Run as a systemd service behind Caddy (HTTPS), both provided in [deploy/](deploy/).

```bash
# 1. Code + venv on the host
sudo mkdir -p /opt/gurobimcp && sudo rsync -a ./ /opt/gurobimcp/
cd /opt/gurobimcp && uv venv .venv && uv pip install --python .venv/bin/python -e .

# 2. Secrets (root-only)
sudo mkdir -p /etc/gurobimcp
sudo tee /etc/gurobimcp/gurobimcp.env >/dev/null <<EOF
FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
JWT_SECRET=$(openssl rand -hex 32)
IDLE_TIMEOUT_MINUTES=15
PORT_RANGE=61100-61200
WORKSPACE_ROOT=/opt/gurobimcp/workspaces
EOF
sudo chmod 600 /etc/gurobimcp/gurobimcp.env

# 3. systemd service (auto-start, restart on failure)
sudo cp deploy/gurobimcp.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now gurobimcp

# 4. Caddy HTTPS reverse proxy (edit the domain in the Caddyfile first)
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Open **only ports 80 and 443** in the cloud firewall / Azure NSG — never the app
port (8000) or the container range (61100–61200). Caddy obtains and renews TLS
certificates automatically. See [deploy/gurobimcp.service](deploy/gurobimcp.service)
and [deploy/Caddyfile](deploy/Caddyfile) for the annotated configs.

## Security model

- Passwords are bcrypt-hashed; Gurobi secrets are Fernet-encrypted at rest and
  never returned or logged (FR-003/004/005).
- Each user is isolated: a dedicated container, loopback port, and `0o700`
  workspace; cross-user access is rejected with `403` (FR-022/025).
- The app and all containers listen on loopback only; HTTPS via Caddy is the lone
  public surface (FR-032/033).
