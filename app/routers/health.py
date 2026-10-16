"""Health & integration-status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_config
from ..database import get_db
from ..providers.dhan import DhanClient
from ..services.credentials import resolve_config

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    cfg = get_config()
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    resolved = resolve_config(db)  # env + DB-stored credentials
    return {
        "status": "ok" if db_ok else "degraded",
        "env": cfg.app_env,
        "database": "ok" if db_ok else "error",
        "integrations": {
            "dhan": resolved.dhan_configured,
            "openai": resolved.openai_configured,
            "news": resolved.news_configured,
        },
    }


@router.get("/health/broker")
def broker_health(db: Session = Depends(get_db)) -> dict:
    return DhanClient(resolve_config(db)).health_check()
