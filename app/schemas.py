"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    username: str
    password: str


class SignalOut(BaseModel):
    id: int
    symbol: str
    direction: str
    product: str
    sell_trade_type: str
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    reward_risk: float
    quality_score: float
    verdict: str
    quantity: int
    capital_required: float
    risk_amount: float
    created_at: datetime
    expires_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class SignalDetailOut(SignalOut):
    score_breakdown: dict[str, Any]
    technical: dict[str, Any]
    fundamental: dict[str, Any]
    news: dict[str, Any]
    provenance: dict[str, Any]
    rejection_reasons: list[str]
    warnings: list[str]


class DashboardOut(BaseModel):
    market_status: str
    last_scan: datetime | None
    qualified_buy: int
    qualified_sell: int
    auto_trading: str
    broker_health: dict[str, Any]
    buys: list[SignalOut]
    sells: list[SignalOut]
    message: str | None = None


class SettingsOut(BaseModel):
    universe: dict[str, Any]
    capital: dict[str, Any]
    auto_trading: dict[str, Any]
    scheduling: dict[str, Any]
    scoring: dict[str, Any]
    policy: dict[str, Any]
    updated_at: datetime | None = None
    # Credential presence only — never the secret values themselves.
    integrations: dict[str, bool] = {}


class SettingsUpdate(BaseModel):
    universe: dict[str, Any] | None = None
    capital: dict[str, Any] | None = None
    auto_trading: dict[str, Any] | None = None
    scheduling: dict[str, Any] | None = None
    scoring: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None


class OrderOut(BaseModel):
    id: int
    symbol: str
    side: str
    product: str
    order_type: str
    quantity: int
    filled_quantity: int
    price: float
    average_price: float
    status: str
    paper: bool
    broker_order_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PositionOut(BaseModel):
    id: int
    symbol: str
    product: str
    quantity: int
    average_price: float
    last_price: float
    unrealized_pnl: float
    paper: bool

    model_config = ConfigDict(from_attributes=True)
