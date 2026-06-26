"""Pydantic request/response schemas (T013).

Auth schemas land here in US1; chat schemas (ChatRequest/ChatResponse/FileRef)
are added in US2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=8)
    grb_access_id: str = Field(min_length=1)
    grb_secret: str = Field(min_length=1)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserPublic(BaseModel):
    """User view safe to return — never includes password or Gurobi secret."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    created_at: datetime


# --- Chat schemas (T024) ---


class FileRef(BaseModel):
    """A file accompanying a chat turn (input or output)."""

    name: str
    path: str | None = None
    content_base64: str | None = None


class ChatRequest(BaseModel):
    conversation_id: str
    agent: str  # validated against Agent in the service to return 400 (FR-011)
    message: str
    # When true, also return the agent's native structuredContent if it emits one
    # (a fixed {"output": ...} envelope; the image accepts no request-side schema).
    structured: bool = False
    input_files: list[FileRef] = Field(default_factory=list)


class ChatResponse(BaseModel):
    conversation_id: str
    agent: str
    text: str | None = None
    structured: dict[str, Any] | None = None
    output_files: list[FileRef] = Field(default_factory=list)
    recovered: bool = False
