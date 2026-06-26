"""ORM models (T012).

Only durable account data is persisted. Live conversation/session state lives
in the in-memory registry (US2), not here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from gurobimcp.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    """A registered person and their (encrypted) Gurobi credentials."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    grb_access_id: Mapped[str] = mapped_column(String, nullable=False)
    grb_secret_enc: Mapped[str] = mapped_column(String, nullable=False)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allocated_port: Mapped[int | None] = mapped_column(Integer)
    container_name: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
