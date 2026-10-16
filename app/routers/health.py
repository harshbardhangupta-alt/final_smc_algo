"""Health & integration-status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_config
from ..database import get_db
from ..providers.dhan import DhanClient

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    cfg = get_config()
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "env": cfg.app_env,
        "database": "ok" if db_ok else "error",
        "integrations": {
            "dhan": cfg.dhan_configured,
            "openai": cfg.openai_configured,
            "news": cfg.news_configured,
        },
    }


@router.get("/health/broker")
def broker_health() -> dict:
    return DhanClient().health_check()
