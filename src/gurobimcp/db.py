"""SQLite persistence: engine, session factory, and declarative base (T006).

Only durable account data is persisted here; live conversation/session state is
held in process memory (see the in-memory registry added with US2).
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from gurobimcp.config import get_settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


_settings = get_settings()
_connect_args = (
    {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
)
engine = create_engine(_settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def init_db() -> None:
    """Create tables for all registered models.

    Models register on ``Base.metadata`` simply by being imported; the import
    below is a no-op until the User model lands with US1.
    """
    try:
        importlib.import_module("gurobimcp.models")
    except ModuleNotFoundError:
        pass
    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
