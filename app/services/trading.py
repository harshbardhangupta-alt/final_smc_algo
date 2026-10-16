"""Optional automated trade execution.

Live auto-trading is OFF by default and gated behind an explicit administrator
confirmation. Every permission and risk check is enforced here in the backend,
not the frontend. Orders are idempotent (keyed by signal), partial fills are
tracked, and uncertain order status pauses new orders for that instrument.

Nothing here places an order based solely on an LLM response: the LLM only
contributed to eligibility upstream; execution depends on deterministic
revalidation of price, funds, limits and signal validity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone

from sqlalchemy.orm import Session

from ..models import AuditLog, Instrument, Order, Settings, Signal
from ..providers import ProviderError, ProviderUnavailable
from ..providers.dhan import DhanClient

log = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    executed: bool
    reason: str
    order_id: int | None = None
    paper: bool = True
    detail: dict | None = None


def _audit(db: Session, action: str, detail: dict, actor: str = "auto-trader") -> None:
    db.add(AuditLog(actor=actor, action=action, detail=detail))
    db.commit()


def execute_signal(
    db: Session, signal: Signal, dhan: DhanClient | None, settings: Settings,
    current_price: float | None = None, now: datetime | None = None,
) -> ExecutionResult:
    """Run the full pre-trade validation pipeline and place a permitted order.

    Returns an :class:`ExecutionResult` describing what happened or why nothing
    was executed. Safe to call repeatedly: an existing order for the signal
    short-circuits (duplicate prevention).
    """
    at = settings.auto_trading or {}
    now = now or datetime.now(timezone.utc)

    # 1. Global gates.
    if at.get("kill_switch", False):
        return ExecutionResult(False, "kill switch engaged")
    if not at.get("enabled", False):
        return ExecutionResult(False, "auto-trading disabled")
    if not at.get("live_confirmed", False) and not at.get("paper_trading", True):
        return ExecutionResult(False, "live execution not confirmed by admin")

    paper = bool(at.get("paper_trading", True))

    # 2. Direction permission.
    if signal.direction == "buy" and not at.get("buy_enabled", True):
        return ExecutionResult(False, "buy orders disabled", paper=paper)
    if signal.direction == "sell" and not at.get("sell_enabled", True):
        return ExecutionResult(False, "sell orders disabled", paper=paper)

    # 3. SELL constraints (Indian market): no multi-day cash short.
    if signal.direction == "sell":
        product = at.get("order_product", "CNC")
        if product not in ("INTRADAY", "MTF"):
            return ExecutionResult(
                False, "SELL swing not executable: multi-day cash short not permitted; "
                       "set order_product to INTRADAY or verified MTF", paper=paper)

    # 4. Duplicate prevention (idempotent by signal).
    client_order_id = f"sig-{signal.id}"
    existing = db.query(Order).filter(Order.client_order_id == client_order_id).first()
    if existing:
        return ExecutionResult(False, "order already exists for signal", existing.id, paper=existing.paper)

    # 5. Uncertain-status guard for the same instrument.
    uncertain = db.query(Order).filter(
        Order.symbol == signal.symbol,
        Order.status.in_(["PENDING", "UNKNOWN"]),
    ).first()
    if uncertain:
        return ExecutionResult(False, f"pending/uncertain order exists for {signal.symbol}", paper=paper)

    # 6. Signal validity / expiry.
    if signal.expires_at and now > _aware(signal.expires_at):
        return ExecutionResult(False, "signal expired", paper=paper)
    if not signal.published or signal.quantity <= 0:
        return ExecutionResult(False, "signal not tradable", paper=paper)

    # 7. Session window (if restricted).
    if not _within_session(at, now):
        return ExecutionResult(False, "outside permitted trading session", paper=paper)

    # 8. Slippage check against a fresh price when available.
    price = current_price
    if price is None and not paper and dhan and dhan.configured:
        price = _fetch_price(db, dhan, signal.symbol)
    if price is not None:
        slippage = abs(price - signal.entry) / signal.entry * 100 if signal.entry else 100.0
        max_slip = float(at.get("max_entry_slippage_pct", 0.5))
        adverse = (signal.direction == "buy" and price > signal.entry) or (
            signal.direction == "sell" and price < signal.entry)
        if adverse and slippage > max_slip:
            return ExecutionResult(False, f"price moved {slippage:.2f}% past entry (> {max_slip}%)", paper=paper)

    # 9. Per-trade capital cap.
    if signal.capital_required > float(at.get("max_capital_per_trade", 1e12)):
        return ExecutionResult(False, "exceeds max capital per trade", paper=paper)

    # 10. Daily trade count limit. (SQLite stores naive UTC; match it.)
    start_of_day = datetime.combine(now.date(), time.min)
    todays = db.query(Order).filter(Order.created_at >= start_of_day).count()
    if todays >= int(at.get("max_trades_per_day", 5)):
        return ExecutionResult(False, "max trades per day reached", paper=paper)

    # --- Place the order (paper or live) -------------------------------------
    return _place(db, signal, dhan, at, paper, client_order_id, price or signal.entry)


def _place(db, signal, dhan, at, paper, client_order_id, exec_price) -> ExecutionResult:
    inst = db.query(Instrument).filter(Instrument.symbol == signal.symbol).first()
    product = at.get("order_product", "CNC")
    side = "BUY" if signal.direction == "buy" else "SELL"

    order = Order(
        signal_id=signal.id, client_order_id=client_order_id, symbol=signal.symbol,
        security_id=inst.security_id if inst else "", side=side, product=product,
        order_type="LIMIT", quantity=signal.quantity, price=signal.entry, paper=paper,
        status="PENDING",
    )
    db.add(order)
    db.commit()

    if paper:
        # Paper fill at the planned entry — clearly flagged as simulated.
        order.status = "FILLED"
        order.filled_quantity = signal.quantity
        order.average_price = signal.entry
        order.raw_response = {"paper": True, "note": "simulated fill"}
        db.commit()
        _audit(db, "paper_order_filled", {"signal": signal.id, "symbol": signal.symbol,
                                          "qty": signal.quantity, "price": signal.entry})
        return ExecutionResult(True, "paper order filled", order.id, paper=True,
                               detail=order.raw_response)

    # Live path.
    if not dhan or not dhan.configured:
        order.status = "REJECTED"
        order.raw_response = {"error": "broker not configured"}
        db.commit()
        return ExecutionResult(False, "broker not configured for live order", order.id, paper=False)

    payload = {
        "transactionType": side,
        "exchangeSegment": inst.segment if inst else "NSE_EQ",
        "productType": product,
        "orderType": "LIMIT",
        "securityId": order.security_id,
        "quantity": signal.quantity,
        "price": signal.entry,
        "correlationId": client_order_id,
    }
    try:
        resp = dhan.place_order(payload)
    except (ProviderUnavailable, ProviderError) as exc:
        # Status uncertain: keep PENDING so the instrument is paused until reconciliation.
        order.status = "UNKNOWN"
        order.raw_response = {"error": str(exc)}
        db.commit()
        _audit(db, "live_order_uncertain", {"signal": signal.id, "error": str(exc)})
        return ExecutionResult(False, f"order status uncertain: {exc}", order.id, paper=False)

    order.broker_order_id = str(resp.get("orderId") or resp.get("order_id") or "")
    order.status = str(resp.get("orderStatus") or resp.get("status") or "PENDING").upper()
    order.raw_response = resp
    db.commit()
    _audit(db, "live_order_placed", {"signal": signal.id, "broker_order_id": order.broker_order_id,
                                     "status": order.status})
    return ExecutionResult(True, "live order submitted", order.id, paper=False, detail=resp)


def reconcile_orders(db: Session, dhan: DhanClient) -> dict:
    """Reconcile open/uncertain live orders against the broker."""
    if not dhan.configured:
        return {"reconciled": 0, "offline": True}
    count = 0
    pending = db.query(Order).filter(
        Order.paper.is_(False), Order.status.in_(["PENDING", "UNKNOWN"]),
    ).all()
    for order in pending:
        ref = order.broker_order_id or order.client_order_id
        if not ref:
            continue
        try:
            resp = dhan.get_order(order.broker_order_id) if order.broker_order_id else None
        except (ProviderUnavailable, ProviderError) as exc:
            log.warning("reconcile failed for %s: %s", order.symbol, exc)
            continue
        if not resp:
            continue
        order.status = str(resp.get("orderStatus") or resp.get("status") or order.status).upper()
        order.filled_quantity = int(resp.get("filledQty") or resp.get("filled_quantity") or order.filled_quantity)
        order.average_price = float(resp.get("averagePrice") or resp.get("average_price") or order.average_price)
        order.raw_response = resp
        count += 1
    db.commit()
    return {"reconciled": count, "offline": False}


def _aware(dt: datetime) -> datetime:
    """Coerce a possibly naive (SQLite-read) datetime to UTC-aware."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _within_session(at: dict, now: datetime) -> bool:
    try:
        start = _parse_time(at.get("session_start", "09:15"))
        end = _parse_time(at.get("session_end", "15:15"))
    except ValueError:
        return True
    # Session times are IST (NSE). Convert the (UTC) timestamp to IST first.
    from datetime import timedelta

    ist = _aware(now) + timedelta(hours=5, minutes=30)
    t = ist.time()
    return start <= t <= end


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def _fetch_price(db, dhan: DhanClient, symbol: str) -> float | None:
    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    if not inst or not inst.security_id:
        return None
    try:
        data = dhan.ltp({inst.segment: [inst.security_id]})
    except (ProviderUnavailable, ProviderError):
        return None
    # Response shape varies; dig for a numeric last price.
    return _dig_price(data)


def _dig_price(data) -> float | None:
    if isinstance(data, dict):
        for key in ("last_price", "ltp", "LTP"):
            if key in data and isinstance(data[key], (int, float)):
                return float(data[key])
        for v in data.values():
            found = _dig_price(v)
            if found is not None:
                return found
    elif isinstance(data, list):
        for v in data:
            found = _dig_price(v)
            if found is not None:
                return found
    return None
