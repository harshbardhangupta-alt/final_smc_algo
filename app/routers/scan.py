"""Scan + universe-sync endpoints (no auth)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import ScanRun, Settings
from ..providers.universe import resolve_universe, sync_instruments
from ..services import scanner

router = APIRouter(prefix="/api", tags=["scan"])


def _run_scan_bg() -> None:
    db = SessionLocal()
    try:
        scanner.run_scan(db)
    finally:
        db.close()


@router.post("/scan")
def trigger_scan(background: BackgroundTasks) -> dict:
    """Trigger a full-universe scan in the background."""
    background.add_task(_run_scan_bg)
    return {"status": "scan started"}


@router.post("/universe/sync")
def universe_sync(db: Session = Depends(get_db)) -> dict:
    """Resolve the configured universe and map instruments to Dhan security ids."""
    settings = db.get(Settings, 1)
    constituents, note = resolve_universe(settings.universe if settings else {})
    summary = sync_instruments(db, constituents)
    summary["note"] = note
    return summary


@router.get("/scan/runs")
def scan_runs(db: Session = Depends(get_db)) -> list[dict]:
    runs = db.query(ScanRun).order_by(ScanRun.id.desc()).limit(20).all()
    return [
        {
            "id": r.id, "started_at": r.started_at, "finished_at": r.finished_at,
            "universe": r.universe, "scanned": r.scanned,
            "qualified_buy": r.qualified_buy, "qualified_sell": r.qualified_sell,
            "status": r.status, "message": r.message,
        }
        for r in runs
    ]
