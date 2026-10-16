"""Scanner-pipeline tests using dependency injection (no network).

Covers: offline behaviour publishes nothing; a qualified candidate is published
with sizing; stale data and critical-news gates prevent publication.
"""

from datetime import datetime, timezone

import pytest

from app.core.analysis import AnalysisResult
from app.core.selection import ScoreInput
from app.core.smc.structure import Trend
from app.core.trade_levels import EntryModel, LevelError, TradeLevels
from app.models import Instrument, Signal
from app.providers.fundamentals import FundamentalsProvider
from app.providers.news import NewsResult
from app.providers.openai_client import ResearchAssessment
from app.services import scanner


def _add_instrument(db, symbol="RELIANCE", sector="ENERGY"):
    inst = Instrument(symbol=symbol, name=symbol, exchange="NSE",
                      security_id="100", segment="NSE_EQ", sector=sector, active=True)
    db.add(inst)
    db.commit()
    return inst


def _good_levels():
    return TradeLevels(
        direction="buy", entry=100.0, stop_loss=95.0, tp1=110.0, tp2=120.0, tp3=130.0,
        risk_per_share=5.0, reward_risk_tp1=2.0, reward_risk_final=6.0,
        entry_model=EntryModel.NORMAL, ok=True, error=LevelError.NONE,
    )


def _good_analysis(symbol="RELIANCE"):
    comps = ScoreInput(1, 1, 1, 1, 1, 1, 1, 1, 1)
    return AnalysisResult(
        symbol=symbol, direction="buy", trend_daily=Trend.BULLISH, trend_weekly=Trend.BULLISH,
        levels=_good_levels(), components=comps, zone=None, stale_data=False,
        liquid_enough=True, latest_ts=datetime.now(timezone.utc), notes=[],
    )


class _FakeNews:
    def __init__(self, ok=True):
        self.ok = ok

    def fetch(self, symbol, name="", max_age_days=14):
        return NewsResult(ok=self.ok, items=[], checked_at=datetime.now(timezone.utc),
                          error="" if self.ok else "offline")


class _FakeResearcher:
    def __init__(self, available=True, critical=False, material=False):
        self._a = available
        self._crit = critical
        self._mat = material

    def assess(self, symbol, direction, evidence):
        if not self._a:
            return ResearchAssessment.unavailable("disabled")
        return ResearchAssessment(
            sentiment="neutral", confidence=0.7, thesis_support="supports",
            material_negative=self._mat, critical_flag=self._crit, summary="ok",
            key_points=[], model="test-model", available=True,
        )


def _fetcher(bundle):
    return lambda inst: bundle


def test_offline_scan_publishes_nothing(db_session):
    _add_instrument(db_session)
    run = scanner.run_scan(
        db_session,
        candle_fetcher=lambda inst: None,          # no data
        researcher=_FakeResearcher(available=False),
        news=_FakeNews(ok=False),
        fundamentals=FundamentalsProvider(),
    )
    assert run.qualified_buy == 0 and run.qualified_sell == 0
    assert db_session.query(Signal).filter(Signal.published.is_(True)).count() == 0


def test_qualified_candidate_published_with_sizing(db_session, monkeypatch):
    _add_instrument(db_session)
    monkeypatch.setattr(scanner, "analyze_symbol", lambda *a, **k: _good_analysis())
    run = scanner.run_scan(
        db_session,
        candle_fetcher=_fetcher({"D": [1], "W": [1]}),  # non-empty -> analysis runs
        researcher=_FakeResearcher(available=True),
        news=_FakeNews(ok=True),
        fundamentals=FundamentalsProvider(),
    )
    assert run.qualified_buy == 1
    sig = db_session.query(Signal).filter(Signal.published.is_(True)).one()
    assert sig.symbol == "RELIANCE" and sig.direction == "buy"
    assert sig.quantity > 0 and sig.capital_required > 0
    assert sig.tp1 < sig.tp2 < sig.tp3 and sig.stop_loss < sig.entry


def test_critical_news_blocks_publication(db_session, monkeypatch):
    _add_instrument(db_session)
    monkeypatch.setattr(scanner, "analyze_symbol", lambda *a, **k: _good_analysis())
    scanner.run_scan(
        db_session,
        candle_fetcher=_fetcher({"D": [1], "W": [1]}),
        researcher=_FakeResearcher(available=True, critical=True),
        news=_FakeNews(ok=True),
        fundamentals=FundamentalsProvider(),
    )
    assert db_session.query(Signal).filter(Signal.published.is_(True)).count() == 0
    sig = db_session.query(Signal).first()
    assert "critical_news" in (sig.rejection_reasons or [])


def test_news_failure_fail_closed_blocks(db_session, monkeypatch):
    _add_instrument(db_session)
    monkeypatch.setattr(scanner, "analyze_symbol", lambda *a, **k: _good_analysis())
    scanner.run_scan(
        db_session,
        candle_fetcher=_fetcher({"D": [1], "W": [1]}),
        researcher=_FakeResearcher(available=False),  # AI unavailable
        news=_FakeNews(ok=False),                     # news failed
        fundamentals=FundamentalsProvider(),
    )
    assert db_session.query(Signal).filter(Signal.published.is_(True)).count() == 0


def test_stale_data_blocks_publication(db_session, monkeypatch):
    _add_instrument(db_session)
    stale = _good_analysis()
    stale.stale_data = True
    monkeypatch.setattr(scanner, "analyze_symbol", lambda *a, **k: stale)
    scanner.run_scan(
        db_session,
        candle_fetcher=_fetcher({"D": [1], "W": [1]}),
        researcher=_FakeResearcher(available=True),
        news=_FakeNews(ok=True),
        fundamentals=FundamentalsProvider(),
    )
    assert db_session.query(Signal).filter(Signal.published.is_(True)).count() == 0


def test_real_engine_produces_directional_signal(db_session, monkeypatch):
    """End-to-end with the REAL analysis engine on an injected uptrend series."""
    from tests.conftest import make_candles, UPTREND_CLOSES
    _add_instrument(db_session)
    bundle = {"D": make_candles(UPTREND_CLOSES), "W": make_candles(UPTREND_CLOSES)}
    scanner.run_scan(
        db_session,
        candle_fetcher=_fetcher(bundle),
        researcher=_FakeResearcher(available=True),
        news=_FakeNews(ok=True),
        fundamentals=FundamentalsProvider(),
    )
    sig = db_session.query(Signal).first()
    assert sig is not None and sig.direction in ("buy", "sell")
