"""Application settings (T005).

All operational knobs are environment-driven so deployment needs no code
changes (FR-027/035). Defaults are dev-friendly; secrets must be supplied via
the environment in any real deployment.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Security ---
    fernet_key: str = Field(
        default="", description="Fernet key used to encrypt Gurobi secrets at rest (FR-004)"
    )
    jwt_secret: str = Field(
        default="", description="HMAC secret used to sign JWT auth tokens (FR-006)"
    )
    jwt_ttl: int = Field(default=3600, ge=60, description="Auth token lifetime in seconds")
    jwt_algorithm: str = Field(default="HS256")

    # --- Persistence ---
    database_url: str = Field(default="sqlite:///./gurobimcp.db")

    # --- Container lifecycle ---
    idle_timeout_minutes: int = Field(
        default=15, ge=1, description="Reap environments idle longer than this (FR-024/035)"
    )
    reaper_interval_seconds: int = Field(default=60, ge=5)
    port_range: str = Field(
        default="61100-61200", description="Inclusive loopback port pool (FR-021)"
    )
    workspace_root: str = Field(
        default="./workspaces", description="Base dir for per-user /workspace mounts (FR-022)"
    )
    mcp_image: str = Field(default="gurobi/mcp:latest")
    container_port: int = Field(default=61095, description="Port the gurobi/mcp image exposes")
    mcp_path: str = Field(
        default="/api/v1/agent/mcp", description="MCP endpoint path inside the image"
    )
    container_mem_limit: str = Field(default="1g")
    loopback_host: str = Field(default="127.0.0.1")

    # --- App ---
    app_host: str = Field(default="127.0.0.1")
    app_port: int = Field(default=8000)

    @field_validator("port_range")
    @classmethod
    def _validate_port_range(cls, v: str) -> str:
        start_s, sep, end_s = v.partition("-")
        if not sep or not start_s.isdigit() or not end_s.isdigit() or int(start_s) > int(end_s):
            raise ValueError("port_range must be 'START-END' with START <= END, e.g. '61100-61200'")
        return v

    @property
    def port_range_bounds(self) -> tuple[int, int]:
        """Return (start, end) inclusive bounds of the loopback port pool."""
        start_s, _, end_s = self.port_range.partition("-")
        return int(start_s), int(end_s)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
