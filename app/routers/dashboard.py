"""Dashboard API: the final qualified BUY/SELL selections + top-bar status."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ScanRun, Settings, Signal
from ..providers.dhan import DhanClient
from ..schemas import DashboardOut, SignalOut

router = APIRouter(prefix="/api", tags=["dashboard"])


def latest_published_signals(db: Session) -> list[Signal]:
    """Latest non-expired published signals, de-duplicated per symbol+direction."""
    now = datetime.now(timezone.utc)
    rows = (
        db.query(Signal)
        .filter(Signal.published.is_(True))
        .order_by(Signal.created_at.desc())
        .limit(500)
        .all()
    )
    seen: set[tuple[str, str]] = set()
    out: list[Signal] = []
    for s in rows:
        if s.expires_at and _aware(s.expires_at) < now:
            continue
        key = (s.symbol, s.direction)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)) -> DashboardOut:
    signals = latest_published_signals(db)
    buys = [s for s in signals if s.direction == "buy"]
    sells = [s for s in signals if s.direction == "sell"]
    buys.sort(key=lambda s: s.quality_score, reverse=True)
    sells.sort(key=lambda s: s.quality_score, reverse=True)

    last_run = db.query(ScanRun).order_by(ScanRun.id.desc()).first()
    settings = db.get(Settings, 1)
    at = (settings.auto_trading if settings else {}) or {}
    auto = "ON" if at.get("enabled") else "OFF"
    if at.get("kill_switch"):
        auto = "KILL-SWITCH"
    elif at.get("enabled") and at.get("paper_trading"):
        auto = "ON (paper)"

    broker = DhanClient().health_check()
    message = None
    if not buys and not sells:
        message = "No qualified trade setups currently available."

    return DashboardOut(
        market_status=_market_status(),
        last_scan=last_run.finished_at if last_run else None,
        qualified_buy=len(buys),
        qualified_sell=len(sells),
        auto_trading=auto,
        broker_health=broker,
        buys=[SignalOut.model_validate(s) for s in buys],
        sells=[SignalOut.model_validate(s) for s in sells],
        message=message,
    )


def _market_status() -> str:
    # NSE cash session 09:15-15:30 IST, Mon-Fri. Compute in IST (UTC+5:30).
    from datetime import timedelta

    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    if ist.weekday() >= 5:
        return "CLOSED (weekend)"
    minutes = ist.hour * 60 + ist.minute
    if 9 * 60 + 15 <= minutes <= 15 * 60 + 30:
        return "OPEN"
    return "CLOSED"
