<!--
SYNC IMPACT REPORT
==================
Version change: (unversioned) → 1.0.0
Bump rationale: MAJOR — initial constitution creation, no prior version.

Modified principles: N/A (all new)

Added sections:
  - Core Principles (5 principles)
  - Technology Stack
  - Development Workflow
  - Governance

Removed sections: N/A (initial draft)

Templates requiring updates:
  - .specify/templates/plan-template.md ✅ No changes required — generic
  - .specify/templates/spec-template.md ✅ No changes required — generic
  - .specify/templates/tasks-template.md ✅ No changes required — generic
  - .specify/templates/checklist-template.md ✅ No changes required — generic

Follow-up TODOs:
  - None — all fields resolved from project context.
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

### II. Optimization Correctness

Gurobi model formulations exposed through MCP tools MUST produce
mathematically valid results. Solver parameters, objective sense, constraint
types, and variable bounds MUST be explicitly defined and documented in the
tool schema. Tools MUST NOT silently ignore infeasibility or unboundedness —
solver status (OPTIMAL, INFEASIBLE, UNBOUNDED, etc.) MUST always be
communicated in structured output.

**Rationale**: Incorrect optimization results propagate into agent decisions
without triggering visible errors. The contract between tool and caller must
be precise about what "success" and "failure" mean for each solver call.

### III. Test-First Development (NON-NEGOTIABLE)

Tests MUST be written before implementation. The cycle is: write test →
confirm it fails (red) → implement → confirm it passes (green) → refactor.
No implementation task may be started without a corresponding failing test.
Unit tests cover model-building logic; integration tests cover full solve
round-trips via the MCP interface.

**Rationale**: Optimization solvers have non-obvious failure modes
(numerical instability, silent constraint violations, degenerate solutions).
Catching these requires tests that run before the implementation exists.

### IV. MCP Contract Testing

Every MCP tool MUST have a contract test verifying its JSON schema, required
fields, and error responses before implementation. Contract tests MUST be
independent of any specific Gurobi license or environment — they test the
MCP interface contract, not the solver outcome. Integration tests MAY
require a Gurobi license and are marked `[integration]` to allow selective
execution.

**Rationale**: Separating contract tests from solver tests allows CI to
validate the API surface on any machine, while solver-dependent tests run
only where a Gurobi license is available.

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
- **MCP SDK**: `mcp` (Anthropic MCP Python SDK)
- **Solver**: Gurobi (via `gurobipy`)
- **Testing**: `pytest` with `pytest-asyncio` for async MCP handlers
- **Linting**: `ruff` for formatting and static analysis
- **Type checking**: `mypy` (strict mode)
- **License requirement**: Gurobi license required for integration tests;
  contract and unit tests MUST run license-free

## Development Workflow

- All features follow the spec → plan → tasks → implement pipeline using
  Spec Kit commands.
- Feature branches follow the `###-feature-name` convention.
- Every PR MUST include a Constitution Check section in the plan verifying
  compliance with all five principles.
- Complexity Tracking table MUST be filled for any deviation from Principle V
  (Simplicity), documenting why the simpler alternative was rejected.
- Integration tests requiring a Gurobi license are marked `[integration]`
  and excluded from the default `pytest` run; they MUST pass in a
  license-enabled environment before merge.
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

**Version**: 1.0.0 | **Ratified**: 2026-06-25 | **Last Amended**: 2026-06-25
