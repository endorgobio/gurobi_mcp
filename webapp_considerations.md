# Web App Considerations — Gurobi MCP Multi-User Backend

This document explains how to test the running service and how to build a chat web
app on top of it. It is written for a frontend/full‑stack developer who has never
seen the backend code.

- **Public endpoint (TLS):** `https://68-211-181-36.sslip.io`
- **Interactive API docs (Swagger UI):** `https://68-211-181-36.sslip.io/docs`
- **OpenAPI spec (machine‑readable):** `https://68-211-181-36.sslip.io/openapi.json`

## What this service is (in one minute)

It's a JSON/REST backend that lets many users each chat, multi‑turn, with one of
three Gurobi optimization agents — **`gurobot`**, **`explainer`**, **`modeler`**.

- Each user **registers with their own Gurobi Intelligence Hub credentials**
  (Access ID + Secret). Those are encrypted at rest and used later to start that
  user's private optimization container.
- You authenticate with a **JWT bearer token** obtained from `/auth/login`.
- A **conversation** is identified by a caller‑supplied `conversation_id` and is
  **bound to a single agent** on its first message (immutable afterward).
- The first message of a conversation **cold‑starts a container** (can take up to a
  few minutes); later turns are fast and keep context.
- Idle containers are reclaimed after ~15 min; the next message **auto‑recovers**
  (a fresh container) and the response is flagged `recovered: true`.

The service is a **proxy** — it runs no solver itself; it relays the agents' replies.

---

## 1. Testing from the VM terminal (on the server itself)

On the VM the app listens on loopback `127.0.0.1:8000` (Caddy sits in front on
443). You can hit either the app directly or the public URL.

```bash
# Direct to the app (bypasses Caddy/TLS):
BASE=http://127.0.0.1:8000

# …or through the public HTTPS entry point:
# BASE=https://68-211-181-36.sslip.io

# Health
curl -s $BASE/health           # {"status":"ok"}

# 1) Register (password >= 8 chars; use REAL Gurobi Hub credentials)
curl -s -X POST $BASE/auth/register -H 'content-type: application/json' -d '{
  "username":"alice","password":"supersecret1",
  "grb_access_id":"YOUR_ACCESS_ID","grb_secret":"YOUR_SECRET"
}'

# 2) Login -> capture JWT
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'content-type: application/json' \
  -d '{"username":"alice","password":"supersecret1"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
echo "$TOKEN"

# 3) Chat (first turn cold-starts the container — be patient)
curl -s -X POST $BASE/chat -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"conversation_id":"c1","agent":"gurobot","message":"In one sentence, what is Gurobi?"}'

# 4) End the conversation (optional)
curl -s -o /dev/null -w '%{http_code}\n' -X POST $BASE/conversations/c1/end \
  -H "Authorization: Bearer $TOKEN"     # 204
```

There is also a ready‑made script: `./scripts/smoke_e2e.sh` (reads Gurobi creds
from `.env`, runs register → login → chat with all three agents).

**Service management on the VM**

```bash
systemctl status gurobimcp caddy          # state
journalctl -u gurobimcp -f                # app logs (live)
journalctl -u caddy -f                    # proxy / TLS logs
sudo systemctl restart gurobimcp          # restart the app
```

---

## 2. Testing from a local machine terminal

Use the **public HTTPS URL** — no SSH tunnel needed.

### macOS / Linux / Git Bash / WSL (bash + curl)

```bash
BASE=https://68-211-181-36.sslip.io

curl -s -X POST $BASE/auth/register -H 'content-type: application/json' -d '{
  "username":"alice","password":"supersecret1",
  "grb_access_id":"YOUR_ACCESS_ID","grb_secret":"YOUR_SECRET"
}'

TOKEN=$(curl -s -X POST $BASE/auth/login -H 'content-type: application/json' \
  -d '{"username":"alice","password":"supersecret1"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s -X POST $BASE/chat -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"conversation_id":"c1","agent":"gurobot","message":"In one sentence, what is Gurobi?"}'
```

### Windows (PowerShell)

```powershell
# On Windows PowerShell 5.1, force modern TLS first (PowerShell 7 doesn't need this):
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$BASE = "https://68-211-181-36.sslip.io"   # define ONCE per session

# 1) Register
$body = @{
  username      = "alice"
  password      = "supersecret1"
  grb_access_id = "YOUR_ACCESS_ID"
  grb_secret    = "YOUR_SECRET"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$BASE/auth/register" -ContentType "application/json" -Body $body

# 2) Login -> token
$login = @{ username = "alice"; password = "supersecret1" } | ConvertTo-Json
$resp  = Invoke-RestMethod -Method Post -Uri "$BASE/auth/login" -ContentType "application/json" -Body $login
$token = $resp.access_token

# 3) Chat (raise the timeout for the cold start)
$headers = @{ Authorization = "Bearer $token" }
$chat = @{ conversation_id = "c1"; agent = "gurobot"; message = "In one sentence, what is Gurobi?" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$BASE/chat" -Headers $headers -ContentType "application/json" -Body $chat -TimeoutSec 600

# Seeing error bodies (Invoke-RestMethod throws on 4xx/5xx):
# try { ... } catch { $_.Exception.Response.StatusCode.value__; $_.ErrorDetails.Message }
```

> Notes: define `$BASE` once per session (a new window forgets it — the symptom is
> *"Invalid URI: hostname could not be parsed"*). Don't use `curl` in PowerShell;
> it's an alias for `Invoke-WebRequest` with different quoting — use the commands above.

---

## 3. Testing with the Swagger UI (`/docs`)

Open **`https://68-211-181-36.sslip.io/docs`** in any browser. It's a clickable form
for every endpoint, generated from the live API.

1. Expand **`POST /auth/register`** → **Try it out** → fill `username`, `password`
   (≥ 8 chars), `grb_access_id`, `grb_secret` → **Execute**. Expect **201**.
2. Expand **`POST /auth/login`** → run it with the same username/password → copy the
   `access_token` from the response body.
3. Click the green **Authorize** button (top‑right) → paste **just the token**
   (Swagger adds the `Bearer ` prefix) → **Authorize** → **Close**.
4. Expand **`POST /chat`** → set `conversation_id` (e.g. `c1`), pick an `agent`,
   type a `message` → **Execute**. The first call is slow (cold start).
5. Try the binding rules: re‑run `/chat` on the same `c1` with a different `agent`
   → **400**; use a new `conversation_id` to start fresh.

This is the fastest way to explore the API and confirm credentials before writing code.

---

## 4. API reference (what the web app will call)

Base URL: `https://68-211-181-36.sslip.io`. All bodies are JSON. Authenticated
endpoints require the header `Authorization: Bearer <access_token>`.

### Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/auth/register` | no | Create an account. |
| `POST` | `/auth/login` | no | Exchange credentials for a JWT. |
| `GET`  | `/auth/me` | yes | Return the current user — handy to validate a token. |
| `POST` | `/chat` | yes | Send a turn to a conversation's bound agent. |
| `POST` | `/conversations/{conversation_id}/end` | yes | Release a conversation's context. |
| `GET`  | `/health` | no | Liveness probe. |

### Request / response shapes

**POST `/auth/register`** → `201`
```jsonc
// request
{ "username": "alice", "password": "supersecret1",   // password minLength 8
  "grb_access_id": "…", "grb_secret": "…" }
// response (UserPublic — never returns the password or Gurobi secret)
{ "id": 1, "username": "alice", "created_at": "2026-06-26T16:00:00Z" }
```

**POST `/auth/login`** → `200`
```jsonc
// request
{ "username": "alice", "password": "supersecret1" }
// response (TokenResponse)
{ "access_token": "eyJ…", "token_type": "bearer", "expires_in": 3600 }
```

**POST `/chat`** → `200`
```jsonc
// request (ChatRequest)
{
  "conversation_id": "c1",        // your thread id; first use binds the agent
  "agent": "gurobot",             // "gurobot" | "explainer" | "modeler"
  "message": "What is Gurobi?",
  "structured": false,            // optional; ask for the agent's structured payload
  "input_files": []               // optional; see "Files" below
}
// response (ChatResponse)
{
  "conversation_id": "c1",
  "agent": "gurobot",
  "text": "Gurobi is …",          // the agent's reply (may be null if purely structured)
  "structured": null,             // object when the agent emitted structuredContent
  "output_files": [],             // files the agent produced (FileRef[])
  "recovered": false              // true if the environment was transparently restarted
}
```

**POST `/conversations/{conversation_id}/end`** → `204` (no body).

**FileRef** (used in `input_files` and `output_files`):
```jsonc
{ "name": "data.csv",             // required
  "path": "/workspace/data.csv",  // optional; path inside the user's workspace
  "content_base64": "…" }         // optional; inline bytes for small files
```

### Status codes & error body

Every error (except request‑validation) returns:
```jsonc
{ "detail": "human-readable message", "code": "stable_machine_code" }
```

| Code | When | `code` values |
|------|------|---------------|
| `200` | Success (`/chat`) | — |
| `201` | Account created | — |
| `204` | Conversation ended | — |
| `400` | Invalid agent name, or trying to switch a conversation's agent | `invalid_agent`, `agent_conflict` |
| `401` | Missing / malformed / expired token, or bad login | `invalid_credentials`, (auth failures) |
| `403` | Using another user's `conversation_id` | `forbidden` |
| `404` | Ending an unknown conversation | `not_found` |
| `409` | Username already taken (register) | `username_taken` |
| `422` | Request body fails validation (e.g. password < 8, missing field) | *FastAPI default — body is `{"detail":[…]}`, NOT the shape above* |
| `424` | Container failed to start, or Gurobi credentials rejected upstream, or agent unreachable | `environment_unavailable`, `agent_unavailable` |
| `503` | Server at capacity (all 101 ports in use) | `capacity_reached` |

> **Watch out:** `422` (validation) uses FastAPI's default error shape
> `{"detail": [ {"loc": …, "msg": …} ]}`, which is different from the `{detail, code}`
> shape of every other error. Handle both.

---

## 5. Building the chat web app — detailed guide

### 5.1 First decision: where do the HTTP calls originate?

This determines whether you need CORS and how you store the token.

- **A) Browser‑direct (SPA):** your React/Vue/Svelte code calls the service directly
  with `fetch`/`axios`. ➜ **You will need CORS enabled on the service** (see 5.8),
  and the JWT lives in the browser.
- **B) Backend‑for‑frontend (recommended for production):** the browser talks to
  *your* server, and *your* server calls this service. ➜ **No CORS needed**
  (server‑to‑server), and the JWT can be kept server‑side (more secure).

If unsure, start with **B** for production hardening, or **A** for the fastest
prototype (ask the backend owner to add your origin to CORS).

### 5.2 Authentication flow

1. **Register** (one‑time per user) — collect `username`, `password`, and the user's
   **Gurobi Hub Access ID + Secret**. Make clear in your UI that the Gurobi
   credentials are required and are the user's own Hub credentials.
2. **Login** → store the `access_token`. It is a **JWT that expires after
   `expires_in` seconds** (default **3600 = 1 hour**).
3. Send `Authorization: Bearer <token>` on every authenticated call.
4. **There is no refresh endpoint.** When the token expires you'll get **401** — send
   the user back through login (or, in architecture B, re‑login server‑side). A good
   UX: track `expires_in`, and on any `401` transparently prompt re‑login.
5. **Token storage:**
   - Architecture A (browser): storing JWTs in `localStorage` is simplest but is
     exposed to XSS. Prefer in‑memory + a short re‑login, or an httpOnly cookie set
     by your own backend.
   - Architecture B: keep the token in the server session; never expose it to JS.

### 5.3 Conversation & agent model (the rules your UI must respect)

- **You generate `conversation_id`.** Use a stable id per chat thread (e.g. a UUID
  created when the user starts a new chat). Reusing the same id continues the thread
  with full context; a new id starts a fresh thread.
- **An agent is bound on the first message** of a conversation and **cannot change**.
  If you send a different `agent` for an existing `conversation_id`, you get **400
  `agent_conflict`**. ➜ In the UI, let the user pick the agent **when starting a new
  chat**, then lock it for that thread.
- **Invalid agent name → 400 `invalid_agent`.** Only `gurobot`, `explainer`,
  `modeler` are valid. Use a dropdown, don't free‑type.
- **One conversation per user is owned by that user.** Another user's token using
  your `conversation_id` gets **403** — not a concern within one user's session, but
  don't share ids across accounts.
- **Ending a thread** (`/conversations/{id}/end`) releases its context. Afterwards the
  same id may be reused and may bind a different agent.

### 5.4 Latency: cold starts, timeouts, and loading UX

- The **first message** of a conversation (or the first after an idle reap) starts a
  container and can take **up to ~5 minutes**. Subsequent turns are quick.
- **Set a long client timeout** for `/chat` — at least **300–360 s** (e.g. `fetch`
  with an `AbortController` at 360 s; PowerShell `-TimeoutSec 600`). A default 30–100 s
  HTTP timeout *will* cut off cold starts.
- **UX:** show a "starting your optimization environment… this can take a minute on
  the first message" state for the first turn, and a normal typing indicator after.
- Because the agent reply streams back only when complete, **there is no token‑by‑token
  streaming** in this API — you get the whole `text` at once. Plan your UI for a
  single response payload, not SSE/word‑by‑word.

### 5.5 The `recovered` flag

- `recovered: true` means the user's environment had been reclaimed (idle) and was
  transparently restarted for this turn. The **prior in‑progress context of that
  thread is gone**, but the call still succeeds.
- **UX:** optionally show a subtle notice like *"Your session was idle and has been
  refreshed; earlier context in this thread may be lost."* Never treat it as an error.

### 5.6 Idle reaping & sessions

- After ~15 minutes with no messages, the user's container is stopped and its
  resources freed. The user's **account and history of conversation_ids are not
  affected** — the next message simply rebuilds the environment (`recovered: true`).
- Don't keep a long‑lived "session" concept on the client beyond the JWT; just send
  the next message when the user is ready.

### 5.7 Error handling → recommended UX

| Status / `code` | Suggested handling |
|-----------------|--------------------|
| `401` | Token missing/expired → route to login; re‑auth and retry. |
| `400 invalid_agent` / `agent_conflict` | Programming/UI error — lock the agent per thread so this can't happen. |
| `403 forbidden` | The `conversation_id` isn't this user's — start a new thread. |
| `404 not_found` | Ending a thread that doesn't exist — ignore or refresh thread list. |
| `409 username_taken` | Registration: ask for a different username. |
| `422` | Show field validation (password ≥ 8, required fields). Remember the different body shape. |
| `424` | "Your optimization environment couldn't start — check your Gurobi credentials and try again." Offer retry; a transient failure may succeed on retry. |
| `503 capacity_reached` | "The service is busy; please try again in a moment." Back off and retry. |

Always read `detail`/`code` for a precise message; fall back to a generic message
for `422`’s array body.

### 5.8 CORS (only relevant for browser‑direct, architecture A)

CORS is a **browser‑only** security rule. It does not affect server‑to‑server calls,
curl, Postman, or PowerShell — which is why all the terminal tests work today.

- **Current state:** the service sends **no CORS headers**. A browser SPA calling it
  directly will be **blocked by the browser** (the request reaches the server, but the
  browser refuses to let your JS read the response), and preflight `OPTIONS` requests
  (triggered by the `Authorization` and `Content-Type: application/json` headers) will
  fail.
- **To enable it:** the backend must add FastAPI `CORSMiddleware` allow‑listing your
  web app's **exact origin(s)** — e.g. `http://localhost:5173` in dev and
  `https://your-app.com` in prod — and allow the `POST`/`OPTIONS` methods plus the
  `Authorization` and `Content-Type` headers. Allow‑list specific origins, **not `*`**,
  because the API carries bearer tokens.
- **Action:** if you go browser‑direct, give the backend owner your origin(s) and ask
  them to add CORS. Until then, use architecture B (your own backend proxies the calls).

### 5.9 Files (optional feature)

- To send input files with a turn, include `input_files: [{ "name": "data.csv",
  "content_base64": "<base64>" }]`. They are written into the user's workspace and made
  available to the agent. Keep inline files small; base64 inflates size ~33%.
- Files the agent produces come back in `output_files` as `FileRef`s; fetch/render them
  according to your UI needs.

### 5.10 Security checklist for the web app

- **Always use HTTPS** (`https://68-211-181-36.sslip.io`) — never downgrade to HTTP.
- **Never log or display** the user's password or Gurobi secret; send them only over
  HTTPS to `/auth/register`.
- **Minimize token exposure** (see 5.2). Prefer a backend‑held token (architecture B)
  for production.
- **Don't hard‑code** one user's Gurobi credentials in the web app — each user enters
  their own at registration.
- Treat the Gurobi Access ID/Secret like passwords in your UI (masked inputs, no
  autocomplete leakage).

### 5.11 Minimal browser client (vanilla JS, architecture A)

```js
const BASE = "https://68-211-181-36.sslip.io";
let token = null;

async function api(path, { method = "GET", body, auth = true, timeoutMs = 360000 } = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);   // long timeout for cold starts
  try {
    const res = await fetch(BASE + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(auth && token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    const data = res.status === 204 ? null : await res.json().catch(() => null);
    if (!res.ok) throw { status: res.status, data };   // data = {detail, code} or 422 array
    return data;
  } finally {
    clearTimeout(t);
  }
}

async function register(u, p, accessId, secret) {
  return api("/auth/register", { method: "POST", auth: false,
    body: { username: u, password: p, grb_access_id: accessId, grb_secret: secret } });
}

async function login(u, p) {
  const r = await api("/auth/login", { method: "POST", auth: false,
    body: { username: u, password: p } });
  token = r.access_token;          // store securely; expires in r.expires_in seconds
  return r;
}

// Keep one conversationId per chat thread; pick the agent once when the thread starts.
async function sendMessage(conversationId, agent, message) {
  try {
    const r = await api("/chat", { method: "POST",
      body: { conversation_id: conversationId, agent, message } });
    if (r.recovered) {/* show "session refreshed" notice */}
    return r.text;                 // render r.text; also inspect r.structured / r.output_files
  } catch (e) {
    if (e.status === 401) {/* token expired -> re-login */}
    else if (e.status === 424) {/* env couldn't start -> show retry */}
    else if (e.status === 503) {/* busy -> back off + retry */}
    throw e;
  }
}
```

For **architecture B**, move `register`/`login`/`sendMessage` to your server (same
calls, same shapes), keep `token` in the server session, and expose your own
thin endpoints to the browser — no CORS required.

---

## 6. Quick reference

- **Endpoint:** `https://68-211-181-36.sslip.io` · **Docs:** `/docs` · **Spec:** `/openapi.json`
- **Agents:** `gurobot`, `explainer`, `modeler` (bound per conversation, immutable)
- **Auth:** `POST /auth/login` → `Authorization: Bearer <token>`, expires in ~1 h, no refresh
- **Chat:** `POST /chat` with `{conversation_id, agent, message}`; first turn is slow (cold start) — use a 300 s+ timeout
- **Recovery:** `recovered: true` = environment was idle‑reclaimed and rebuilt; not an error
- **CORS:** not enabled yet — required only for browser‑direct calls; ask the backend owner to allow‑list your origin
- **Errors:** `{detail, code}` everywhere except `422` (validation) which is `{detail: [...]}`
