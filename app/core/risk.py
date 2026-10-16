"""Capital allocation, position sizing and portfolio risk checks.

All currency values are INR. This module never allocates more than the stricter
of the configured allocation and risk limits allow, and it accounts for
estimated round-trip costs. It is deterministic and unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import floor
from typing import Literal


class AllocationMethod(str, Enum):
    FIXED = "fixed"              # fixed INR per trade
    RISK_BASED = "risk_based"    # size from entry-to-stop distance
    HYBRID = "hybrid"            # stricter of fixed vs risk-based


@dataclass
class CapitalConfig:
    total_capital: float = 1_000_000.0
    cash_capital: float = 1_000_000.0
    mtf_capital: float = 0.0
    allocation_method: AllocationMethod = AllocationMethod.HYBRID
    allocation_per_trade: float = 100_000.0      # used by FIXED / HYBRID
    max_risk_per_trade_pct: float = 1.0          # % of total capital at risk
    max_positions: int = 10
    max_aggregate_risk_pct: float = 5.0
    max_sector_exposure_pct: float = 30.0
    max_gross_exposure_pct: float = 100.0
    cash_reserve_pct: float = 10.0
    min_free_funds: float = 0.0
    per_stock_cap: float = 0.0                   # 0 => no explicit per-stock cap
    cost_pct: float = 0.2                        # round-trip estimated cost %


@dataclass
class PortfolioState:
    open_positions: int = 0
    open_risk_amount: float = 0.0                # INR currently at risk
    gross_exposure: float = 0.0                  # INR deployed
    sector_exposure: dict[str, float] = field(default_factory=dict)
    used_cash: float = 0.0


class SizingError(str, Enum):
    NONE = "none"
    MAX_POSITIONS = "max_positions_reached"
    NO_FREE_FUNDS = "insufficient_free_funds"
    ZERO_QTY = "zero_quantity"
    AGG_RISK = "aggregate_risk_exceeded"
    SECTOR = "sector_exposure_exceeded"
    GROSS = "gross_exposure_exceeded"


@dataclass(frozen=True)
class PositionPlan:
    quantity: int
    capital_required: float
    risk_amount: float
    estimated_cost: float
    method: AllocationMethod
    product: str
    ok: bool
    error: SizingError = SizingError.NONE


def size_position(
    entry: float,
    stop_loss: float,
    config: CapitalConfig,
    portfolio: PortfolioState,
    sector: str = "UNKNOWN",
    product: Literal["CASH", "MTF"] = "CASH",
) -> PositionPlan:
    """Compute a safe quantity honouring every configured limit.

    Returns a plan with ``ok=False`` and a specific error when any mandatory
    limit would be breached. Missing or impossible sizing never silently
    becomes a tradable position.
    """
    risk_per_share = abs(entry - stop_loss)
    if entry <= 0 or risk_per_share <= 0:
        return _fail(config, product, SizingError.ZERO_QTY)

    if portfolio.open_positions >= config.max_positions:
        return _fail(config, product, SizingError.MAX_POSITIONS)

    # Available cash after reserve and minimum free-funds constraints.
    reserve = config.total_capital * config.cash_reserve_pct / 100
    pool = config.mtf_capital if product == "MTF" else config.cash_capital
    free = pool - portfolio.used_cash - reserve
    free = min(free, config.total_capital - portfolio.used_cash - config.min_free_funds)
    if free <= 0:
        return _fail(config, product, SizingError.NO_FREE_FUNDS)

    # Candidate capital by allocation method.
    fixed_cap = config.allocation_per_trade
    risk_budget = config.total_capital * config.max_risk_per_trade_pct / 100
    risk_cap = (risk_budget / risk_per_share) * entry  # capital implied by risk budget

    if config.allocation_method == AllocationMethod.FIXED:
        target_capital = fixed_cap
    elif config.allocation_method == AllocationMethod.RISK_BASED:
        target_capital = risk_cap
    else:  # HYBRID -> stricter (smaller) of the two
        target_capital = min(fixed_cap, risk_cap)

    if config.per_stock_cap > 0:
        target_capital = min(target_capital, config.per_stock_cap)
    target_capital = min(target_capital, free)

    quantity = floor(target_capital / entry)
    if quantity <= 0:
        return _fail(config, product, SizingError.ZERO_QTY)

    capital_required = quantity * entry
    risk_amount = quantity * risk_per_share
    estimated_cost = capital_required * config.cost_pct / 100

    # Aggregate risk check.
    agg_risk_limit = config.total_capital * config.max_aggregate_risk_pct / 100
    if portfolio.open_risk_amount + risk_amount > agg_risk_limit:
        return _fail(config, product, SizingError.AGG_RISK)

    # Gross exposure check.
    gross_limit = config.total_capital * config.max_gross_exposure_pct / 100
    if portfolio.gross_exposure + capital_required > gross_limit:
        return _fail(config, product, SizingError.GROSS)

    # Sector exposure check.
    sector_limit = config.total_capital * config.max_sector_exposure_pct / 100
    current_sector = portfolio.sector_exposure.get(sector, 0.0)
    if current_sector + capital_required > sector_limit:
        return _fail(config, product, SizingError.SECTOR)

    return PositionPlan(
        quantity=quantity,
        capital_required=round(capital_required, 2),
        risk_amount=round(risk_amount, 2),
        estimated_cost=round(estimated_cost, 2),
        method=config.allocation_method,
        product=product,
        ok=True,
    )


def _fail(config: CapitalConfig, product: str, error: SizingError) -> PositionPlan:
    return PositionPlan(
        quantity=0, capital_required=0.0, risk_amount=0.0, estimated_cost=0.0,
        method=config.allocation_method, product=product, ok=False, error=error,
    )
