<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 2.0.0
Bump rationale: MAJOR — Principles II and IV redefined and the solver removed
from the Technology Stack to match the actual architecture: this project is a
multi-user backend/proxy to the gurobi/mcp Intelligence Hub containers, not a
solver-exposing MCP server. It links no `gurobipy` and runs no solver.

Modified principles:
  - II. "Optimization Correctness" → "Faithful Proxying & Result Integrity"
  - IV. "MCP Contract Testing" → "Contract Testing" (REST contract + [integration])

Modified sections:
  - Technology Stack — removed Solver/`gurobipy`; license → Hub credentials
  - Development Workflow — Gurobi license → Intelligence Hub credentials

Known remaining solver-flavored wording (intentionally left for a future pass):
  - Principle III still references "model-building logic" / "full solve
    round-trips"; revisit if III is amended.

Templates requiring updates:
  - .specify/templates/*.md ✅ No changes required — generic

Follow-up TODOs:
  - Consider realigning Principle III wording with the proxy architecture.
-->

# Gurobi MCP Constitution

## Core Principles

### I. MCP Protocol Compliance

Every tool exposed by this server MUST conform to the Model Context Protocol
specification. Tool definitions MUST include typed input schemas, accurate
descriptions, and structured output. Protocol messages MUST validate against
the MCP schema before transmission. No undocumented or ad-hoc tool interfaces
are permitted — all capabilities MUST be discoverable via standard MCP
tool-listing.

**Rationale**: Clients (AI agents, LLMs) depend on contract-exact tool
definitions to generate correct invocations. Deviations silently corrupt model
reasoning and are nearly impossible to debug.

### II. Faithful Proxying & Result Integrity

This project is a backend/proxy: it does NOT build, run, or solve optimization
models and links no `gurobipy`. It MUST relay the Intelligence Hub agents'
outputs — text, structured content, files, status, and errors — faithfully and
without alteration, and MUST NOT silently drop or reinterpret them. Upstream
failures (authentication, agent, or processing errors) MUST always be surfaced
to the caller rather than swallowed. The Hub agents may help build and code
optimization models, but this service never executes them.

**Rationale**: As a proxy, the service's correctness is measured by fidelity,
not by solver outcomes it never computes. Silently altering or dropping an
agent's response corrupts the caller's reasoning exactly as a wrong solver
result would, so faithful relay is the core contract.

### III. Test-First Development (NON-NEGOTIABLE)

Tests MUST be written before implementation. The cycle is: write test →
confirm it fails (red) → implement → confirm it passes (green) → refactor.
No implementation task may be started without a corresponding failing test.
Unit tests cover model-building logic; integration tests cover full solve
round-trips via the MCP interface.

**Rationale**: Optimization solvers have non-obvious failure modes
(numerical instability, silent constraint violations, degenerate solutions).
Catching these requires tests that run before the implementation exists.

### IV. Contract Testing

The service's external contract — its REST/JSON API — MUST have contract tests
verifying request/response schemas, required fields, status codes, and error
bodies before implementation. Contract tests MUST be independent of any
Intelligence Hub credentials, network access, or running container — they test
the API surface, not live agent behavior. Tests that exercise real containers
and the Hub agents over the MCP client session MAY require Hub credentials and
are marked `[integration]` to allow selective execution.

**Rationale**: Separating contract tests from credential/network-dependent
tests lets CI validate the API surface on any machine, while integration tests
run only where Hub access is available.

### V. Simplicity

Prefer fewer, well-scoped tools over many narrow-purpose ones. Each MCP tool
MUST have a single, clearly stated responsibility. YAGNI — do not add
parameters, outputs, or tools for hypothetical future use cases. Complexity
in any tool definition MUST be justified against a concrete user scenario in
the feature spec.

**Rationale**: MCP tool lists are presented to language models with limited
context windows. Tool bloat degrades model reasoning quality and increases
maintenance surface with no corresponding benefit.

## Technology Stack

- **Runtime**: Python 3.11+
- **MCP SDK**: `mcp` (Anthropic MCP Python SDK) — used as a **client** to the
  upstream `gurobi/mcp` containers; this project exposes no MCP tools of its own
- **Solver**: none. This service does NOT link `gurobipy` and never runs a
  solver. The Intelligence Hub agents (gurobot, explainer, modeler) may help
  build and code models, but the service does not execute them
- **Testing**: `pytest` with `pytest-asyncio` for async handlers
- **Linting**: `ruff` for formatting and static analysis
- **Type checking**: `mypy` (strict mode)
- **Credential requirement**: valid Intelligence Hub credentials (Access ID/
  Secret) required only for `[integration]` tests; contract and unit tests MUST
  run without any Hub access

## Development Workflow

- All features follow the spec → plan → tasks → implement pipeline using
  Spec Kit commands.
- Feature branches follow the `###-feature-name` convention.
- Every PR MUST include a Constitution Check section in the plan verifying
  compliance with all five principles.
- Complexity Tracking table MUST be filled for any deviation from Principle V
  (Simplicity), documenting why the simpler alternative was rejected.
- Integration tests requiring Intelligence Hub credentials are marked
  `[integration]` and excluded from the default `pytest` run; they MUST pass in
  a credential-enabled environment before merge.
- Commits MUST be atomic: one logical change per commit, with a descriptive
  message referencing the task ID (e.g., `feat(T012): implement solve tool`).

## Governance

This constitution supersedes all other development guidelines. Amendments
require:

1. A documented rationale explaining the change and which principle is
   affected.
2. A version bump following semantic versioning:
   - **MAJOR**: principle removal, redefinition, or backward-incompatible
     governance change.
   - **MINOR**: new principle added or material expansion of existing guidance.
   - **PATCH**: clarifications, wording fixes, or non-semantic refinements.
3. All dependent templates reviewed for consistency after amendment.
4. The Sync Impact Report (HTML comment at file top) updated to reflect the
   amendment.

All PRs and code reviews MUST verify compliance with the five Core Principles.
Non-compliance blocks merge unless formally justified in the Complexity
Tracking table and approved by the project owner.

**Version**: 2.0.0 | **Ratified**: 2026-06-25 | **Last Amended**: 2026-06-25
