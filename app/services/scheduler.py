"""Background scan scheduler (APScheduler).

Runs the full-universe scan on the configured interval. Market-hours gating is
applied when enabled. The scheduler is a thin wrapper so the scan logic stays in
:mod:`app.services.scanner` and remains independently testable.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from ..config import get_config
from ..database import SessionLocal
from ..models import Settings
from . import scanner

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_JOB_ID = "full_universe_scan"


def _market_open_now(settings: Settings, now: datetime) -> bool:
    sch = settings.scheduling or {}
    if not sch.get("market_hours_only", True):
        return True
    try:
        hh, mm = sch.get("market_open", "09:15").split(":")
        oh, om = sch.get("market_close", "15:30").split(":")
        open_t, close_t = time(int(hh), int(mm)), time(int(oh), int(om))
    except ValueError:
        return True
    t = now.timetz().replace(tzinfo=None)
    # Weekdays only (Mon-Fri).
    return now.weekday() < 5 and open_t <= t <= close_t


def _scheduled_scan() -> None:
    db = SessionLocal()
    try:
        settings = db.get(Settings, 1)
        if settings and not _market_open_now(settings, datetime.now(timezone.utc)):
            log.debug("Skipping scan: outside market hours")
            return
        scanner.run_scan(db)
    except Exception as exc:  # noqa: BLE001
        log.exception("Scheduled scan failed: %s", exc)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    cfg = get_config()
    if not cfg.scheduler_enabled:
        log.info("Scheduler disabled via config")
        return None
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _scheduled_scan, "interval", minutes=cfg.scan_interval_minutes,
        id=_JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
    )
    _scheduler.start()
    log.info("Scheduler started: scan every %d min", cfg.scan_interval_minutes)
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("Scheduler stopped")
