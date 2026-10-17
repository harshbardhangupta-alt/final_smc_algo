"""Shared test fixtures.

A temporary SQLite database is configured via environment variables *before*
the application modules import their engine. Helper builders create deterministic
candle series for the core-engine tests.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Configure an isolated temp DB + deterministic secrets BEFORE importing app.
_TMPDIR = tempfile.mkdtemp(prefix="smc_test_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMPDIR}/test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

from app.core.candles import Candle  # noqa: E402

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_candles(closes, *, wick: float = 1.0, volume: float = 3_000_000.0,
                 start: datetime = BASE, step_days: int = 1) -> list[Candle]:
    """Build candles from a close path; highs/lows derive from close + wick.

    Deriving wicks from the close (not open) avoids spurious ties between
    adjacent candles so fractal swings form cleanly.
    """
    out: list[Candle] = []
    prev = closes[0]
    for i, c in enumerate(closes):
        out.append(Candle(
            ts=start + timedelta(days=i * step_days),
            open=prev, high=c + wick, low=c - wick, close=c, volume=volume,
        ))
        prev = c
    return out


# A clean legged uptrend that produces confirmed swings + bullish BOS.
UPTREND_CLOSES = [100, 104, 108, 112, 107, 103, 109, 116, 123, 130,
                  124, 119, 127, 135, 143, 152, 146, 140, 150, 160, 172, 185]

# A legged downtrend (mirror) producing bearish structure.
DOWNTREND_CLOSES = [185, 181, 177, 173, 178, 182, 176, 169, 162, 155,
                    161, 166, 158, 150, 142, 133, 139, 145, 135, 125, 113, 100]


@pytest.fixture
def uptrend():
    return make_candles(UPTREND_CLOSES)


@pytest.fixture
def downtrend():
    return make_candles(DOWNTREND_CLOSES)


@pytest.fixture
def db_session():
    """Fresh DB session with tables created and defaults seeded."""
    from app.database import SessionLocal, engine, Base
    from app.models import Settings
    from app.settings_defaults import default_settings

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if db.get(Settings, 1) is None:
        db.add(Settings(id=1, **default_settings()))
        db.commit()
    try:
        yield db
    finally:
        db.close()
