"""Pydantic request/response schemas (T013).

Auth schemas land here in US1; chat schemas (ChatRequest/ChatResponse/FileRef)
are added in US2.
"""

from __future__ import annotations

from datetime import datetime

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
