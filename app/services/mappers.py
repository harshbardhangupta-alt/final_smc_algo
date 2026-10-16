"""Map admin-tunable settings dicts into the deterministic-core config objects."""

from __future__ import annotations

from ..core.analysis import AnalysisConfig
from ..core.risk import AllocationMethod, CapitalConfig
from ..core.selection import ScoreThresholds
from ..core.trade_levels import EntryModel, LevelConfig


def level_config(scoring: dict) -> LevelConfig:
    entry_model = EntryModel(scoring.get("entry_model", "normal"))
    return LevelConfig(
        entry_model=entry_model,
        stop_buffer_pct=float(scoring.get("stop_buffer_pct", 0.25)),
        max_entry_deviation_pct=float(scoring.get("max_entry_deviation_pct", 1.5)),
        min_reward_risk=float(scoring.get("min_reward_risk", 2.0)),
        max_risk_pct=float(scoring.get("max_risk_pct", 8.0)),
    )


def analysis_config(scoring: dict, universe: dict, scheduling: dict) -> AnalysisConfig:
    return AnalysisConfig(
        min_avg_traded_value=float(universe.get("min_avg_traded_value", 5_000_000.0)),
        staleness_days=int(scheduling.get("staleness_days", 5)),
        level_config=level_config(scoring),
    )


def capital_config(capital: dict) -> CapitalConfig:
    return CapitalConfig(
        total_capital=float(capital.get("total_capital", 1_000_000.0)),
        cash_capital=float(capital.get("cash_capital", 1_000_000.0)),
        mtf_capital=float(capital.get("mtf_capital", 0.0)),
        allocation_method=AllocationMethod(capital.get("allocation_method", "hybrid")),
        allocation_per_trade=float(capital.get("allocation_per_trade", 100_000.0)),
        max_positions=int(capital.get("max_positions", 10)),
        max_risk_per_trade_pct=float(capital.get("max_risk_per_trade_pct", 1.0)),
        max_aggregate_risk_pct=float(capital.get("max_aggregate_risk_pct", 5.0)),
        max_sector_exposure_pct=float(capital.get("max_sector_exposure_pct", 30.0)),
        max_gross_exposure_pct=float(capital.get("max_gross_exposure_pct", 100.0)),
        cash_reserve_pct=float(capital.get("cash_reserve_pct", 10.0)),
        min_free_funds=float(capital.get("min_free_funds", 0.0)),
        per_stock_cap=float(capital.get("per_stock_cap", 0.0)),
        cost_pct=float(capital.get("cost_pct", 0.2)),
    )


def score_thresholds(scoring: dict) -> ScoreThresholds:
    t = scoring.get("thresholds", {})
    return ScoreThresholds(
        premium=float(t.get("premium", 85.0)),
        qualified=float(t.get("qualified", 75.0)),
        watchlist=float(t.get("watchlist", 65.0)),
    )
