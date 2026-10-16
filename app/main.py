"""FastAPI application factory.

Wires configuration, database, routers, static assets, the HTML pages and the
background scanner. On startup it creates tables, seeds the admin user and the
default settings singleton, and (optionally) starts the scheduler.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_config
from .database import SessionLocal, init_db
from .logging_config import configure_logging
from .models import Settings
from .routers import dashboard, health, orders, scan, settings as settings_router, stocks
from .security import ensure_admin_user
from .services.scheduler import shutdown_scheduler, start_scheduler
from .settings_defaults import default_settings

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        ensure_admin_user(db)
        if db.get(Settings, 1) is None:
            db.add(Settings(id=1, **default_settings()))
            db.commit()
            log.info("Seeded default settings")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    configure_logging(cfg.log_level)
    _seed()
    scheduler = start_scheduler()
    log.info("Application started (env=%s)", cfg.app_env)
    try:
        yield
    finally:
        if scheduler is not None:
            shutdown_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI-Powered NSE Stock Selection & Trading System",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(dashboard.router)
    app.include_router(scan.router)
    app.include_router(settings_router.router)
    app.include_router(stocks.router)
    app.include_router(orders.router)

    static_dir = BASE_DIR / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def page_dashboard(request: Request):
        return TEMPLATES.TemplateResponse(request, "dashboard.html", {"active": "dashboard"})

    @app.get("/stock/{signal_id}", response_class=HTMLResponse)
    def page_detail(request: Request, signal_id: int):
        return TEMPLATES.TemplateResponse(
            request, "detail.html", {"active": "dashboard", "signal_id": signal_id}
        )

    @app.get("/settings", response_class=HTMLResponse)
    def page_settings(request: Request):
        return TEMPLATES.TemplateResponse(request, "settings.html", {"active": "settings"})

    @app.get("/orders", response_class=HTMLResponse)
    def page_orders(request: Request):
        return TEMPLATES.TemplateResponse(request, "orders.html", {"active": "orders"})

    return app


app = create_app()
