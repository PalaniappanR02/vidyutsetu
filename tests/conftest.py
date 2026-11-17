"""Shared pytest fixtures.

Every test gets its own in-memory SQLite database so stored meter history and
persisted runs can never leak between tests (or into the repository database).
"""

import os

os.environ.setdefault("VIDYUTSETU_ENV", "test")
os.environ.setdefault("VIDYUTSETU_AUTH_MODE", "disabled")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import database


def _memory_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


# Bind the module-level engine to a scratch in-memory database before any test
# module imports backend.main, so importing the app never touches vidyutsetu.db.
database.engine = _memory_engine()
database.SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=database.engine,
)
database.Base.metadata.create_all(bind=database.engine)


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    """Fresh schema per test, with no rows carried over."""
    engine = _memory_engine()
    database.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(
        database,
        "SessionLocal",
        sessionmaker(autocommit=False, autoflush=False, bind=engine),
    )
    yield
    engine.dispose()
