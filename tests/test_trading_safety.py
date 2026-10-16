"""Auto-trading safety tests: OFF by default, kill switch, idempotency, gates."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Instrument, Order, Settings, Signal
from app.services import trading


def _signal(db, direction="buy", qty=100, published=True, expired=False):
    now = datetime.now(timezone.utc)
    sig = Signal(
        symbol="RELIANCE", direction=direction, product="CASH",
        entry=100.0, stop_loss=95.0, tp1=110, tp2=120, tp3=130, reward_risk=6.0,
        quality_score=90, verdict="premium", published=published, quantity=qty,
        capital_required=qty * 100.0, risk_amount=qty * 5.0,
        created_at=now, expires_at=now - timedelta(minutes=1) if expired else now + timedelta(hours=4),
    )
    db.add(sig)
    db.add(Instrument(symbol="RELIANCE", security_id="100", segment="NSE_EQ", sector="ENERGY"))
    db.commit()
    return sig


def _settings(db, **auto):
    s = db.get(Settings, 1)
    at = dict(s.auto_trading)
    # Widen the trading session so these tests are deterministic at any run time.
    at.setdefault("session_start", "00:00")
    at.setdefault("session_end", "23:59")
    at.update(auto)
    s.auto_trading = at
    db.commit()
    return s


def test_auto_trading_off_by_default(db_session):
    sig = _signal(db_session)
    s = db_session.get(Settings, 1)
    assert s.auto_trading["enabled"] is False  # default OFF
    res = trading.execute_signal(db_session, sig, None, s)
    assert not res.executed and res.reason == "auto-trading disabled"
    assert db_session.query(Order).count() == 0


def test_kill_switch_blocks_everything(db_session):
    sig = _signal(db_session)
    s = _settings(db_session, enabled=True, paper_trading=True, kill_switch=True)
    res = trading.execute_signal(db_session, sig, None, s)
    assert not res.executed and "kill switch" in res.reason


def test_paper_order_fills_and_is_flagged(db_session):
    sig = _signal(db_session)
    s = _settings(db_session, enabled=True, paper_trading=True)
    res = trading.execute_signal(db_session, sig, None, s)
    assert res.executed and res.paper
    order = db_session.query(Order).one()
    assert order.paper and order.status == "FILLED" and order.filled_quantity == sig.quantity


def test_duplicate_order_prevented(db_session):
    sig = _signal(db_session)
    s = _settings(db_session, enabled=True, paper_trading=True)
    first = trading.execute_signal(db_session, sig, None, s)
    assert first.executed
    second = trading.execute_signal(db_session, sig, None, s)
    assert not second.executed and "already exists" in second.reason
    assert db_session.query(Order).count() == 1


def test_expired_signal_not_executed(db_session):
    sig = _signal(db_session, expired=True)
    s = _settings(db_session, enabled=True, paper_trading=True)
    res = trading.execute_signal(db_session, sig, None, s)
    assert not res.executed and res.reason == "signal expired"


def test_sell_swing_blocked_without_intraday_or_mtf(db_session):
    sig = _signal(db_session, direction="sell")
    s = _settings(db_session, enabled=True, paper_trading=True, order_product="CNC")
    res = trading.execute_signal(db_session, sig, None, s)
    assert not res.executed and "short" in res.reason.lower()


def test_sell_allowed_with_intraday(db_session):
    sig = _signal(db_session, direction="sell")
    s = _settings(db_session, enabled=True, paper_trading=True, order_product="INTRADAY")
    res = trading.execute_signal(db_session, sig, None, s)
    assert res.executed and res.paper


def test_slippage_guard_rejects_adverse_move(db_session):
    sig = _signal(db_session, direction="buy")
    s = _settings(db_session, enabled=True, paper_trading=True, max_entry_slippage_pct=0.5)
    # Price 102 is +2% above entry 100 (adverse for a buy) -> reject.
    res = trading.execute_signal(db_session, sig, None, s, current_price=102.0)
    assert not res.executed and "past entry" in res.reason


def test_live_requires_confirmation(db_session):
    sig = _signal(db_session)
    # paper off + not confirmed -> blocked before any order.
    s = _settings(db_session, enabled=True, paper_trading=False, live_confirmed=False)
    res = trading.execute_signal(db_session, sig, None, s)
    assert not res.executed and "confirmed" in res.reason


def test_max_capital_per_trade_enforced(db_session):
    sig = _signal(db_session, qty=1000)  # capital 100,000
    s = _settings(db_session, enabled=True, paper_trading=True, max_capital_per_trade=50_000)
    res = trading.execute_signal(db_session, sig, None, s)
    assert not res.executed and "max capital" in res.reason
