"""FastAPI application entry point (T008).

Foundational app: lifespan wiring (logging + DB init), a structured error
handler, and a liveness probe. Auth, chat, container, and reaper wiring arrive
in later phases (US1–US4).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from gurobimcp.config import get_settings
from gurobimcp.db import init_db
from gurobimcp.errors import AppError
from gurobimcp.logging import configure_logging

logger = logging.getLogger("gurobimcp")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    logger.info("Starting gurobimcp on %s:%s", settings.app_host, settings.app_port)
    init_db()
    # NOTE: idle reaper (US3) and orphan-container reconciliation are wired later.
    yield
    logger.info("Shutting down gurobimcp")


app = FastAPI(
    title="Gurobi MCP Multi-User Backend",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(AppError)
async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


# Routers (auth lands with US1; chat with US2). Imported here, after AppError
# and the app are defined, to keep module import order acyclic.
from gurobimcp.auth.routes import router as auth_router  # noqa: E402

app.include_router(auth_router)
