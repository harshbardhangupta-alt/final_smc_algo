"""Position-sizing and portfolio-limit tests."""

from app.core.risk import (
    AllocationMethod,
    CapitalConfig,
    PortfolioState,
    SizingError,
    size_position,
)


def base_config(**kw) -> CapitalConfig:
    defaults = dict(
        total_capital=1_000_000, cash_capital=1_000_000, allocation_per_trade=100_000,
        max_risk_per_trade_pct=1.0, max_positions=10, cash_reserve_pct=10.0,
    )
    defaults.update(kw)
    return CapitalConfig(**defaults)


def test_fixed_allocation_quantity():
    cfg = base_config(allocation_method=AllocationMethod.FIXED)
    plan = size_position(100.0, 95.0, cfg, PortfolioState())
    assert plan.ok and plan.quantity == 1000  # 100000 / 100
    assert plan.capital_required == 100_000


def test_risk_based_allocation_respects_risk_budget():
    cfg = base_config(allocation_method=AllocationMethod.RISK_BASED, allocation_per_trade=1_000_000)
    # risk budget = 1% of 1,000,000 = 10,000; risk/share = 5 -> qty 2000, risk 10000.
    plan = size_position(100.0, 95.0, cfg, PortfolioState())
    assert plan.ok
    assert abs(plan.risk_amount - 10_000) < 100


def test_hybrid_takes_stricter_allocation():
    cfg = base_config(allocation_method=AllocationMethod.HYBRID, allocation_per_trade=50_000)
    plan = size_position(100.0, 95.0, cfg, PortfolioState())
    # Fixed 50,000 is stricter than risk-implied capital -> qty 500.
    assert plan.ok and plan.quantity == 500


def test_max_positions_enforced():
    cfg = base_config(max_positions=2)
    plan = size_position(100.0, 95.0, cfg, PortfolioState(open_positions=2))
    assert not plan.ok and plan.error == SizingError.MAX_POSITIONS


def test_aggregate_risk_enforced():
    cfg = base_config(allocation_method=AllocationMethod.FIXED, max_aggregate_risk_pct=1.0)
    # Existing risk already near the 10,000 cap.
    pf = PortfolioState(open_risk_amount=9_000)
    plan = size_position(100.0, 95.0, cfg, pf)  # new risk 5000 -> exceeds 10000 cap
    assert not plan.ok and plan.error == SizingError.AGG_RISK


def test_sector_exposure_enforced():
    cfg = base_config(allocation_method=AllocationMethod.FIXED, max_sector_exposure_pct=5.0)
    pf = PortfolioState(sector_exposure={"IT": 40_000})
    plan = size_position(100.0, 95.0, cfg, pf, sector="IT")  # 40k+100k > 50k cap
    assert not plan.ok and plan.error == SizingError.SECTOR


def test_insufficient_free_funds():
    cfg = base_config(allocation_method=AllocationMethod.FIXED)
    pf = PortfolioState(used_cash=950_000)  # reserve 100k leaves negative free
    plan = size_position(100.0, 95.0, cfg, pf)
    assert not plan.ok and plan.error == SizingError.NO_FREE_FUNDS


def test_zero_quantity_when_price_above_allocation():
    cfg = base_config(allocation_method=AllocationMethod.FIXED, allocation_per_trade=50)
    plan = size_position(100.0, 95.0, cfg, PortfolioState())
    assert not plan.ok and plan.error == SizingError.ZERO_QTY


def test_never_sizes_with_invalid_stop():
    cfg = base_config()
    plan = size_position(100.0, 100.0, cfg, PortfolioState())  # zero risk/share
    assert not plan.ok and plan.error == SizingError.ZERO_QTY
