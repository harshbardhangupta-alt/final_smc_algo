"""Default runtime settings seeded into the Settings singleton on first run.

These are the admin-tunable policies. Auto-trading and MTF are OFF by default,
and the news policy fails closed, as required by the operational-safety rules.
"""

from __future__ import annotations

DEFAULT_UNIVERSE = {
    "selected": "NIFTY500",            # NIFTY50 | NIFTY100 | NIFTY500 | CUSTOM
    "custom_symbols": [],              # list of NSE symbols when selected == CUSTOM
    "min_price": 20.0,
    "min_avg_traded_value": 5_000_000.0,
    "min_avg_volume": 50_000.0,
    "max_spread_pct": 1.0,
}

DEFAULT_CAPITAL = {
    "total_capital": 1_000_000.0,
    "cash_capital": 1_000_000.0,
    "mtf_capital": 0.0,
    "allocation_method": "hybrid",     # fixed | risk_based | hybrid
    "allocation_per_trade": 100_000.0,
    "max_positions": 10,
    "max_risk_per_trade_pct": 1.0,
    "max_aggregate_risk_pct": 5.0,
    "max_sector_exposure_pct": 30.0,
    "max_gross_exposure_pct": 100.0,
    "max_daily_loss_pct": 3.0,
    "max_drawdown_pct": 15.0,
    "max_leverage": 1.0,
    "cash_reserve_pct": 10.0,
    "min_free_funds": 0.0,
    "per_stock_cap": 0.0,
    "cost_pct": 0.2,
}

DEFAULT_AUTO_TRADING = {
    "enabled": False,                  # LIVE auto-trading OFF by default
    "paper_trading": True,             # safe default
    "mtf_enabled": False,              # MTF OFF by default
    "buy_enabled": True,
    "sell_enabled": True,
    "max_capital_per_trade": 100_000.0,
    "max_trades_per_day": 5,
    "max_daily_loss": 30_000.0,
    "max_open_exposure": 500_000.0,
    "order_product": "CNC",            # CNC (delivery) | INTRADAY | MTF
    "permitted_instruments": "equity",
    "session_start": "09:15",
    "session_end": "15:15",
    "max_entry_slippage_pct": 0.5,
    "kill_switch": False,
    "live_confirmed": False,           # explicit admin confirmation before first live run
}

DEFAULT_SCHEDULING = {
    "scan_interval_minutes": 30,
    "market_hours_only": True,
    "market_open": "09:15",
    "market_close": "15:30",
    "news_refresh_minutes": 60,
    "fundamentals_refresh_hours": 24,
    "signal_expiry_minutes": 240,
    "max_concurrency": 6,
    "retry_attempts": 3,
}

DEFAULT_SCORING = {
    "weights": {
        "htf_alignment": 15.0,
        "market_structure": 15.0,
        "supply_demand": 15.0,
        "displacement_fvg": 10.0,
        "liquidity": 10.0,
        "sr_confluence": 10.0,
        "entry_confirmation": 10.0,
        "reward_risk": 10.0,
        "data_quality": 5.0,
    },
    "thresholds": {"premium": 85.0, "qualified": 75.0, "watchlist": 65.0},
    "min_reward_risk": 2.0,
    "entry_model": "normal",           # normal | conservative | aggressive(off)
    "stop_buffer_pct": 0.25,
    "max_entry_deviation_pct": 1.5,
    "max_risk_pct": 8.0,
}

DEFAULT_POLICY = {
    # News / fundamental decision policy.
    "news_fail_closed": True,          # block NEW trades if news check fails
    "critical_news_action": "reject",  # reject | suspend
    "reject_buy_on_material_negative": True,
    "require_fundamentals": False,      # if True, missing fundamentals => watchlist
    "max_sector_correlated": 2,         # cap on correlated picks per sector
}


def default_settings() -> dict:
    return {
        "universe": DEFAULT_UNIVERSE,
        "capital": DEFAULT_CAPITAL,
        "auto_trading": DEFAULT_AUTO_TRADING,
        "scheduling": DEFAULT_SCHEDULING,
        "scoring": DEFAULT_SCORING,
        "policy": DEFAULT_POLICY,
    }
