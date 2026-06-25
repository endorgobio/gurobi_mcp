# Gurobi MCP Multi-User Backend

A FastAPI backend that lets multiple users each run their own isolated
`gurobi/mcp` container against their own Gurobi Intelligence Hub credentials,
and chat multi-turn with the three Hub agents (`gurobot`, `explainer`,
`modeler`). This service is a **proxy**: it builds and solves no optimization
models itself and links no `gurobipy`.

See [specs/001-multiuser-mcp-backend/](specs/001-multiuser-mcp-backend/) for the
spec, plan, and tasks.

> Status: scaffolding (Phases 1–2 implemented). Full setup/run/deploy
> documentation is added in a later task (T041).

## Development

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/pytest        # license-free unit + contract tests
```
