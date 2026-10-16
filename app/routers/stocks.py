"""Stock-detail endpoint: concise technical / news / fundamental / risk view."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Signal
from ..schemas import SignalDetailOut

router = APIRouter(prefix="/api", tags=["stocks"])


@router.get("/signals/{signal_id}", response_model=SignalDetailOut)
def signal_detail(signal_id: int, db: Session = Depends(get_db)) -> SignalDetailOut:
    s = db.get(Signal, signal_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Signal not found")
    return SignalDetailOut.model_validate(s)


@router.get("/stocks/{symbol}", response_model=SignalDetailOut)
def latest_for_symbol(symbol: str, db: Session = Depends(get_db)) -> SignalDetailOut:
    s = (
        db.query(Signal)
        .filter(Signal.symbol == symbol.upper())
        .order_by(Signal.created_at.desc())
        .first()
    )
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No signal for symbol")
    return SignalDetailOut.model_validate(s)
