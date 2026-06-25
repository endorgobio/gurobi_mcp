# Feature Specification: Gurobi MCP Multi-User Backend

**Feature Branch**: `001-multiuser-mcp-backend`

**Created**: 2026-06-25

**Status**: Draft

**Input**: User description: "consider the attached file to write the specifications" (Gurobi MCP Multi-User Backend brief + Azure VM + MCP server documentation)

## User Scenarios & Testing *(mandatory)*

<!--
  User journeys ordered by importance. Each is independently testable and
  delivers a viable slice of value on its own.
-->

### User Story 1 - Register and authenticate with personal Gurobi credentials (Priority: P1)

A new user signs up for the service by providing a username/email, a password, and their own Gurobi Intelligence Hub credentials (Access ID and Secret). The system stores their account securely and lets them sign in afterward to obtain a session token that grants access to the chat capabilities.

**Why this priority**: Without an account and an authenticated session bound to the user's own Gurobi credentials, no other capability can function. This is the foundational entry point and the minimum that delivers any value (a securely stored, retrievable account).

**Independent Test**: Can be fully tested by registering a new account, signing in to receive a session token, and confirming that protected endpoints reject requests without a valid token and accept them with one — without ever needing to start a container.

**Acceptance Scenarios**:

1. **Given** no existing account for an email, **When** the user submits valid signup details including Gurobi Access ID and Secret, **Then** the account is created, the password is stored in a non-reversible form, the Gurobi Secret is stored in encrypted form, and the user receives a success confirmation.
2. **Given** an existing account, **When** the user signs in with correct credentials, **Then** they receive a time-limited session token.
3. **Given** an existing account, **When** the user signs in with an incorrect password, **Then** access is denied and no token is issued.
4. **Given** a signup attempt with an email that is already registered, **When** the user submits, **Then** the request is rejected with a clear "already registered" message.
5. **Given** a protected endpoint, **When** a request arrives without a valid session token, **Then** the request is rejected as unauthorized.

---

### User Story 2 - Chat with the Gurobi agents over a multi-turn conversation (Priority: P2)

An authenticated user starts a conversation and sends a message directed at one of the three Gurobi agents (Gurobot, Explainer, or Modeler). On the first message of a conversation the system provisions the user's own isolated environment connected to their Gurobi credentials, keeps that environment alive across turns, and returns the agent's reply. The user continues the conversation across multiple messages and receives context-aware responses.

**Why this priority**: This is the core product value — letting users actually use the Gurobi agents. It depends on US1 (authentication) but, once authenticated, delivers the central experience.

**Independent Test**: Can be tested by authenticating, opening a conversation against one agent, sending two or more sequential messages, and confirming each returns a coherent reply and that the conversation stays bound to the same agent throughout.

**Acceptance Scenarios**:

1. **Given** an authenticated user with no active environment, **When** they send their first message in a new conversation to a chosen agent, **Then** the system provisions their isolated environment on demand and returns the agent's reply.
2. **Given** an active conversation bound to one agent, **When** the user sends a follow-up message, **Then** the reply reflects the prior turns of the same conversation (context is retained).
3. **Given** a conversation already bound to one agent, **When** the user attempts to direct a message in that same conversation to a different agent, **Then** the system enforces the original binding and rejects or prevents the agent switch.
4. **Given** an authenticated user, **When** they request a structured-output response for a message, **Then** the reply is returned in the requested structured form in addition to or instead of free-form text.
5. **Given** two different authenticated users chatting at the same time, **When** each sends messages, **Then** each user's messages are served only by their own isolated environment and credentials, with no cross-user data exposure.

---

### User Story 3 - Transparent recovery after idle shutdown (Priority: P3)

A user returns to a conversation after a period of inactivity during which their environment was automatically stopped to free resources. The user sends their next message and receives a normal reply without having to manually restart anything; the response indicates that recovery occurred.

**Why this priority**: Improves reliability and user experience and is essential for sustainable resource use on a constrained host, but the product is usable for demos without it. It builds on US2.

**Independent Test**: Can be tested by starting a conversation, forcing or waiting for the idle shutdown of the environment, then sending another message in the same conversation and confirming the reply succeeds and is flagged as recovered.

**Acceptance Scenarios**:

1. **Given** a user environment that has been idle beyond the configured timeout, **When** the background reaper runs, **Then** the idle environment is stopped and its resources are released.
2. **Given** a conversation whose environment was stopped while idle, **When** the user sends a new message, **Then** the system transparently re-provisions the environment, retries the message, returns a normal reply, and marks the response as recovered.
3. **Given** an environment that is actively in use, **When** the reaper runs, **Then** the active environment is not stopped.

---

### Edge Cases

- What happens when a user signs up with Gurobi credentials that are invalid or expired? The system should surface an authentication/licensing failure from the agent backend rather than hanging, and should not leave a broken environment running.
- What happens when the host has no free port in the allocated range (all concurrent slots in use)? New environment provisioning must fail gracefully with a clear "capacity reached, try again later" message rather than crashing.
- What happens when the host runs out of memory/CPU while provisioning a new environment? Provisioning must fail safely and report a transient error.
- What happens when a user sends a message to a conversation ID that does not belong to them? The request must be rejected as unauthorized.
- What happens when provisioning succeeds but the agent backend never becomes ready within a reasonable startup window? The request times out with a clear error and the half-started environment is cleaned up.
- What happens when the session token has expired mid-conversation? The user is required to re-authenticate; the conversation can resume afterward.
- What happens if the reaper stops an environment at the exact moment a message is being processed? The in-flight request either completes or fails cleanly, and the next message recovers.

## Requirements *(mandatory)*

### Functional Requirements

#### Authentication & Account Management

- **FR-001**: System MUST allow a new user to register an account with a unique identifier (email/username), a password, and their personal Gurobi Intelligence Hub credentials (Access ID and Secret).
- **FR-002**: System MUST store user passwords in a non-reversible (hashed) form and MUST NOT store them in plaintext.
- **FR-003**: System MUST store each user's Gurobi Secret in encrypted form at rest and decrypt it only when needed to provision that user's environment.
- **FR-004**: System MUST reject signup when the chosen identifier is already registered, with a clear message.
- **FR-005**: System MUST allow a registered user to sign in with their credentials and, on success, issue a time-limited session token.
- **FR-006**: System MUST deny sign-in for incorrect credentials without revealing whether the identifier or the password was wrong.
- **FR-007**: System MUST protect all chat and conversation endpoints so they are accessible only with a valid, unexpired session token.
- **FR-008**: System MUST reject any request bearing an invalid, malformed, or expired session token as unauthorized.

#### Chat & Conversations

- **FR-009**: System MUST let an authenticated user start a conversation directed at exactly one of the three available agents: Gurobot, Explainer, or Modeler.
- **FR-010**: System MUST provision the user's isolated environment on demand when the first message of a conversation is sent, and reuse the same environment for subsequent messages.
- **FR-011**: System MUST keep a user's agent session alive across multiple conversation turns so that conversational context is preserved.
- **FR-012**: System MUST enforce, for the lifetime of a conversation, that all messages are handled by the agent the conversation was originally bound to, and MUST prevent switching agents within a conversation.
- **FR-013**: System MUST support a basic chat option that returns the agent's free-form text reply.
- **FR-014**: System MUST support a structured-output option that returns the agent's reply in a caller-requested structured form.
- **FR-015**: System MUST associate every conversation with the owning user and reject access to a conversation by any other user.
- **FR-016**: System MUST return a clear, user-facing error when the agent backend reports an authentication, licensing, or processing failure.

#### Isolation & Resource Management

- **FR-017**: System MUST run at most one active environment per user at any time.
- **FR-018**: System MUST expose each user environment only on the local host (loopback), never on a publicly reachable interface, allocating from the reserved port range 61100–61200.
- **FR-019**: System MUST give each user a separate file workspace that is not shared with or visible to other users' environments.
- **FR-020**: System MUST fail provisioning gracefully and return a clear capacity message when no environment slot/port is available.
- **FR-021**: System MUST track the last-activity time of each user environment.

#### Idle Reaping & Recovery

- **FR-022**: System MUST run a background process that stops any user environment that has been idle longer than a configurable timeout (default 15 minutes).
- **FR-023**: System MUST NOT stop an environment that is actively serving a request or within the idle threshold.
- **FR-024**: System MUST, when a message arrives for a conversation whose environment was stopped, transparently re-provision the environment, retry the message, and return a normal reply.
- **FR-025**: System MUST indicate in the response when a transparent recovery occurred (a recovered=true flag).
- **FR-026**: System MUST release all resources (port, workspace handles, compute) belonging to a stopped environment so they can be reused.

#### Configuration & Deployment

- **FR-027**: System MUST allow the idle timeout to be configured via an operational setting without code changes.
- **FR-028**: System MUST be deployable as a managed long-running service that starts automatically and restarts on failure.
- **FR-029**: System MUST be reachable by users through a reverse proxy that terminates external access, while the per-user environments remain bound to loopback only.

### Key Entities *(include if feature involves data)*

- **User Account**: Represents a registered person. Key attributes: unique identifier (email/username), hashed password, encrypted Gurobi Access ID/Secret, creation time. Owns conversations and at most one active environment.
- **Session Token**: A time-limited proof of authentication issued at sign-in and presented on protected requests. Bound to one user, has an expiry.
- **Conversation**: A multi-turn exchange owned by one user and permanently bound to one agent (Gurobot, Explainer, or Modeler). Holds ordered turns and the context carried across them.
- **User Environment**: The user's isolated, on-demand runtime connected to their Gurobi credentials. Key attributes: owning user, loopback port from the reserved range, dedicated file workspace, current state (running/stopped), last-activity timestamp.
- **Message Turn**: A single user message and its agent reply within a conversation, optionally including a structured-output payload and a recovered indicator.
- **Agent**: One of the three fixed Gurobi capabilities — Gurobot, Explainer, Modeler — that a conversation can be bound to.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user can go from starting signup to receiving their first agent reply in under 5 minutes on first use.
- **SC-002**: Returning users receive an agent reply to a follow-up message in an already-warm conversation within 10 seconds for typical requests.
- **SC-003**: 100% of stored passwords and Gurobi Secrets are unreadable in plaintext if the underlying data store is inspected directly.
- **SC-004**: No user can ever read, reach, or be served by another user's environment, conversation, or workspace (0 cross-user data exposure incidents in testing).
- **SC-005**: At least the documented number of concurrent users (bounded by the 101-port range and host capacity) can each hold an independent active conversation without interference.
- **SC-006**: 95% of messages sent to a conversation whose environment was idle-stopped succeed transparently on the next attempt and are correctly flagged as recovered.
- **SC-007**: Environments idle beyond the configured timeout are stopped within one reaper cycle, and their resources become available for reuse.
- **SC-008**: An attempt to switch agents mid-conversation is blocked 100% of the time.
- **SC-009**: The service automatically restarts and resumes accepting authenticated requests after an unexpected process termination, with no manual intervention.

## Assumptions

- The three agents (Gurobot, Explainer, Modeler) are provided by the user's own Gurobi Intelligence Hub account via their personal credentials; the system proxies to them and does not implement the agents itself.
- Each user supplies valid Gurobi Intelligence credentials at signup; validating those credentials is the responsibility of the Gurobi backend, and the system surfaces any failure rather than pre-validating.
- The deployment target is a single host (the described Azure VM, 2 vCPU / 8 GB RAM) for the development environment; concurrency limits are bounded by host resources and the 101-port range (61100–61200).
- "One container per user" maps to "one isolated environment per user"; the spec treats it as an isolation boundary rather than mandating a specific runtime technology.
- Session tokens use a standard, industry-typical expiry (e.g., on the order of hours) configurable by operators; the exact value is an operational detail.
- Conversation and message history retention follows standard practice for the development environment; long-term archival/export is out of scope for this version.
- External transport security (TLS) is handled at the reverse-proxy layer; per-user environments are never exposed beyond loopback.
- Administrative concerns (billing, quotas beyond capacity limits, multi-host scaling, account recovery/password reset) are out of scope for this version.
- Password-reset, email verification, and account deletion flows are out of scope for this version unless added later.
