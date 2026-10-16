"""SQLAlchemy engine / session setup.

SQLite for local development (default), PostgreSQL in production — selected
purely by ``DATABASE_URL``. Tables are created at startup; Alembic migrations
are provided for production schema management.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_config


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = get_config().database_url
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        # Ensure the directory for a file-based SQLite DB exists.
        if ":///" in url:
            path = url.split(":///", 1)[1]
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, future=True, connect_args=connect_args)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (idempotent). Alembic is preferred in production."""
    from . import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
