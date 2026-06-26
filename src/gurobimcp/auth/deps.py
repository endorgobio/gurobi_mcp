"""Authentication dependency (T015): Bearer token -> current User.

FR-007/008: protected endpoints require a valid, unexpired token; missing,
malformed, or expired tokens are rejected as 401.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from gurobimcp.auth import security
from gurobimcp.config import Settings, get_settings
from gurobimcp.db import get_db
from gurobimcp.errors import AppError
from gurobimcp.models import User


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError("Not authenticated", status_code=401, code="unauthorized")
    token = authorization.split(" ", 1)[1].strip()
    try:
        subject = security.decode_access_token(
            token, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
    except security.TokenError as exc:
        raise AppError("Invalid or expired token", status_code=401, code="unauthorized") from exc

    user = db.execute(select(User).where(User.id == int(subject))).scalar_one_or_none()
    if user is None:
        raise AppError("Invalid or expired token", status_code=401, code="unauthorized")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
