"""Shared pytest fixtures (T009).

Provides an isolated in-memory SQLite session and a TestClient with the DB
dependency overridden, so license-free unit/contract tests need no real
database, Docker, or Intelligence Hub access.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from gurobimcp.db import Base, get_db
from gurobimcp.main import app


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """A fresh in-memory database shared across connections for one test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    # Register any defined models on the metadata before creating tables.
    try:
        importlib.import_module("gurobimcp.models")
    except ModuleNotFoundError:
        pass
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, class_=Session
    )
    session = testing_session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """A TestClient with the get_db dependency overridden to the test session."""

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
