"""SQLAlchemy ORM models.

Covers runtime settings (a singleton row), instrument mapping, scan runs, the
final published signals with full provenance, orders, positions and an audit
log for settings changes and trade execution.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Settings(Base):
    """Singleton runtime configuration (id == 1).

    JSON blobs hold the tunable policy groups so the admin can change them
    without code changes: universe, capital/risk, auto-trading, scheduling,
    scoring weights/thresholds and the news/fundamental decision policy.
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    universe: Mapped[dict] = mapped_column(JSON, default=dict)
    capital: Mapped[dict] = mapped_column(JSON, default=dict)
    auto_trading: Mapped[dict] = mapped_column(JSON, default=dict)
    scheduling: Mapped[dict] = mapped_column(JSON, default=dict)
    scoring: Mapped[dict] = mapped_column(JSON, default=dict)
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("exchange", "symbol", name="uq_exchange_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    security_id: Mapped[str] = mapped_column(String(32), default="")
    segment: Mapped[str] = mapped_column(String(32), default="NSE_EQ")
    sector: Mapped[str] = mapped_column(String(64), default="UNKNOWN")
    tick_size: Mapped[float] = mapped_column(Float, default=0.05)
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    mtf_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    universe: Mapped[str] = mapped_column(String(32), default="")
    scanned: Mapped[int] = mapped_column(Integer, default=0)
    qualified_buy: Mapped[int] = mapped_column(Integer, default=0)
    qualified_sell: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="running")
    message: Mapped[str] = mapped_column(Text, default="")

    signals: Mapped[list["Signal"]] = relationship(back_populates="scan_run")


class Signal(Base):
    """A qualified (or rejected) candidate with full trade template & provenance.

    Only rows with ``published=True`` appear on the dashboard. Rejected rows are
    retained for auditability but hidden from the main table.
    """

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int | None] = mapped_column(ForeignKey("scan_runs.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # buy / sell
    product: Mapped[str] = mapped_column(String(16), default="CASH")
    sell_trade_type: Mapped[str] = mapped_column(String(32), default="")  # intraday/mtf/analytical

    entry: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss: Mapped[float] = mapped_column(Float, default=0.0)
    tp1: Mapped[float] = mapped_column(Float, default=0.0)
    tp2: Mapped[float] = mapped_column(Float, default=0.0)
    tp3: Mapped[float] = mapped_column(Float, default=0.0)
    reward_risk: Mapped[float] = mapped_column(Float, default=0.0)

    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str] = mapped_column(String(16), default="reject")
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    quantity: Mapped[int] = mapped_column(Integer, default=0)
    capital_required: Mapped[float] = mapped_column(Float, default=0.0)
    risk_amount: Mapped[float] = mapped_column(Float, default=0.0)

    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    technical: Mapped[dict] = mapped_column(JSON, default=dict)
    fundamental: Mapped[dict] = mapped_column(JSON, default=dict)
    news: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    rejection_reasons: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scan_run: Mapped["ScanRun"] = relationship(back_populates="signals")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    broker_order_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    security_id: Mapped[str] = mapped_column(String(32), default="")
    side: Mapped[str] = mapped_column(String(8))  # BUY / SELL
    product: Mapped[str] = mapped_column(String(16), default="CASH")
    order_type: Mapped[str] = mapped_column(String(16), default="LIMIT")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    average_price: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    paper: Mapped[bool] = mapped_column(Boolean, default=True)
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    security_id: Mapped[str] = mapped_column(String(32), default="")
    product: Mapped[str] = mapped_column(String(16), default="CASH")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    average_price: Mapped[float] = mapped_column(Float, default=0.0)
    last_price: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    paper: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Secret(Base):
    """Encrypted credential storage (admin-managed from the UI).

    Values are stored encrypted at rest (Fernet, keyed from SECRET_KEY) and are
    NEVER returned to the browser in plaintext — only masked previews and
    presence flags. DB-stored secrets override the corresponding ``.env`` value.
    """

    __tablename__ = "secrets"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_encrypted: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
