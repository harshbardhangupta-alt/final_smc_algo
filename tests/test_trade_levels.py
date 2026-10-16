"""Trade-level tests: correct BUY/SELL prices, direction, tick, and rejections."""

from datetime import datetime, timezone

from app.core.smc.levels import Level
from app.core.smc.zones import Zone
from app.core.trade_levels import (
    EntryModel,
    LevelConfig,
    LevelError,
    compute_levels,
    round_to_tick,
)

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _demand(top=99.0, bottom=96.0):
    return Zone(5, TS, "demand", top, bottom, "1D", 1.8, invalidation_level=bottom)


def _supply(top=104.0, bottom=101.0):
    return Zone(6, TS, "supply", top, bottom, "1D", 1.8, invalidation_level=top)


def test_round_to_tick():
    assert round_to_tick(100.04) == 100.05
    assert round_to_tick(100.023) == 100.0
    assert round_to_tick(100.01) == 100.0
    assert round_to_tick(100.08) == 100.1


def test_buy_levels_direction_and_order():
    levels = [Level(105, "resistance", 2), Level(112, "resistance", 1),
              Level(120, "resistance", 3), Level(95, "support", 2)]
    L = compute_levels("buy", 100.0, _demand(), levels, 96.0, LevelConfig())
    assert L.ok
    assert L.stop_loss < L.entry < L.tp1 < L.tp2 < L.tp3
    assert L.reward_risk_final >= 2.0


def test_sell_levels_direction_and_order():
    levels = [Level(95, "support", 2), Level(88, "support", 1),
              Level(80, "support", 3), Level(106, "resistance", 1)]
    L = compute_levels("sell", 100.0, _supply(), levels, 104.0, LevelConfig())
    assert L.ok
    assert L.tp3 < L.tp2 < L.tp1 < L.entry < L.stop_loss
    assert L.reward_risk_final >= 2.0


def test_reject_insufficient_targets():
    levels = [Level(105, "resistance", 2), Level(112, "resistance", 1)]  # only 2
    L = compute_levels("buy", 100.0, _demand(), levels, 96.0, LevelConfig())
    assert not L.ok and L.error == LevelError.INSUFFICIENT_TARGETS


def test_reject_low_reward_risk():
    # Targets barely above entry -> RR below the configured minimum.
    levels = [Level(100.5, "resistance", 1), Level(101.0, "resistance", 1),
              Level(101.5, "resistance", 1)]
    L = compute_levels("buy", 100.0, _demand(top=99, bottom=90), levels, 90.0,
                       LevelConfig(min_reward_risk=2.0, max_risk_pct=50.0))
    assert not L.ok and L.error == LevelError.LOW_RR


def test_reject_risk_too_high():
    levels = [Level(105, "resistance", 1), Level(112, "resistance", 1), Level(120, "resistance", 1)]
    # Stop far below entry -> risk% exceeds max_risk_pct.
    L = compute_levels("buy", 100.0, _demand(top=99, bottom=50), levels, 50.0,
                       LevelConfig(max_risk_pct=8.0))
    assert not L.ok and L.error == LevelError.RISK_TOO_HIGH


def test_reject_invalid_stop_for_buy():
    # Zone bottom above entry makes a valid buy stop impossible.
    bad_zone = Zone(5, TS, "demand", top=101, bottom=100.5, timeframe="1D",
                    displacement_ratio=1.5, invalidation_level=100.5)
    levels = [Level(105, "resistance", 1), Level(112, "resistance", 1), Level(120, "resistance", 1)]
    L = compute_levels("buy", 100.0, bad_zone, levels, 100.5, LevelConfig())
    assert not L.ok and L.error == LevelError.INVALID_STOP


def test_reject_price_ran_too_far_from_zone_entry():
    levels = [Level(130, "resistance", 1), Level(140, "resistance", 1), Level(150, "resistance", 1)]
    # Conservative entry at zone top (99) but price already at 110 (>1.5% away).
    L = compute_levels("buy", 110.0, _demand(top=99, bottom=96), levels, 96.0,
                       LevelConfig(entry_model=EntryModel.CONSERVATIVE, max_entry_deviation_pct=1.5))
    assert not L.ok and L.error == LevelError.PRICE_TOO_FAR


def test_no_zone_and_no_swing_rejected():
    L = compute_levels("buy", 100.0, None, [], None, LevelConfig())
    assert not L.ok and L.error == LevelError.NO_ZONE
