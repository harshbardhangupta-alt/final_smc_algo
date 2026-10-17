"""Orders & positions: monitoring + execution / kill-switch controls (no auth)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Order, Position, Settings, Signal
from ..providers.dhan import DhanClient
from ..schemas import OrderOut, PositionOut
from ..services import trading
from ..services.credentials import resolve_config

router = APIRouter(prefix="/api", tags=["orders"])

_ACTOR = "admin"


@router.get("/orders", response_model=list[OrderOut])
def list_orders(db: Session = Depends(get_db)) -> list[OrderOut]:
    rows = db.query(Order).order_by(Order.id.desc()).limit(100).all()
    return [OrderOut.model_validate(r) for r in rows]


@router.get("/positions", response_model=list[PositionOut])
def list_positions(db: Session = Depends(get_db)) -> list[PositionOut]:
    rows = db.query(Position).order_by(Position.id.desc()).all()
    return [PositionOut.model_validate(r) for r in rows]


@router.post("/orders/execute/{signal_id}")
def execute(signal_id: int, db: Session = Depends(get_db)) -> dict:
    """Manually run the pre-trade pipeline for a signal (respects all gates)."""
    signal = db.get(Signal, signal_id)
    if signal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Signal not found")
    settings = db.get(Settings, 1)
    result = trading.execute_signal(db, signal, DhanClient(resolve_config(db)), settings)
    db.add(AuditLog(actor=_ACTOR, action="manual_execute",
                    detail={"signal": signal_id, "executed": result.executed, "reason": result.reason}))
    db.commit()
    return {
        "executed": result.executed, "reason": result.reason,
        "order_id": result.order_id, "paper": result.paper,
    }


@router.post("/kill-switch")
def kill_switch(on: bool = True, db: Session = Depends(get_db)) -> dict:
    """Engage/disengage the emergency kill switch (blocks all new orders)."""
    settings = db.get(Settings, 1)
    at = dict(settings.auto_trading or {})
    at["kill_switch"] = on
    settings.auto_trading = at
    db.add(AuditLog(actor=_ACTOR, action="kill_switch", detail={"on": on}))
    db.commit()
    return {"kill_switch": on}


@router.post("/orders/reconcile")
def reconcile(db: Session = Depends(get_db)) -> dict:
    return trading.reconcile_orders(db, DhanClient(resolve_config(db)))
