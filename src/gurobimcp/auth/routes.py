"""Auth routes (T016): register, login, and a protected probe.

FR-001 register; FR-002 duplicate-username rejection (409); FR-004 secret
encrypted at rest; FR-006 generic login failure (401) without revealing which
factor was wrong; FR-007 protected endpoint (/auth/me).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from gurobimcp.auth import security
from gurobimcp.auth.deps import CurrentUser
from gurobimcp.config import Settings, get_settings
from gurobimcp.db import get_db
from gurobimcp.errors import AppError
from gurobimcp.models import User
from gurobimcp.schemas import LoginRequest, RegisterRequest, TokenResponse, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    existing = db.execute(
        select(User).where(User.username == payload.username)
    ).scalar_one_or_none()
    if existing is not None:
        raise AppError("Username already registered", status_code=409, code="username_taken")

    user = User(
        username=payload.username,
        password_hash=security.hash_password(payload.password),
        grb_access_id=payload.grb_access_id,
        grb_secret_enc=security.encrypt_secret(payload.grb_secret, settings.fernet_key),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    user = db.execute(
        select(User).where(User.username == payload.username)
    ).scalar_one_or_none()
    # Same generic error whether the user is unknown or the password is wrong (FR-006).
    if user is None or not security.verify_password(payload.password, user.password_hash):
        raise AppError("Invalid username or password", status_code=401, code="invalid_credentials")

    token = security.create_access_token(
        subject=str(user.id),
        secret=settings.jwt_secret,
        ttl=settings.jwt_ttl,
        algorithm=settings.jwt_algorithm,
    )
    return TokenResponse(access_token=token, expires_in=settings.jwt_ttl)


@router.get("/me", response_model=UserPublic)
def me(current_user: CurrentUser) -> User:
    return current_user
