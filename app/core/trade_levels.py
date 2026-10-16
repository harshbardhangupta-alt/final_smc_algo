"""Deterministic entry / stop-loss / take-profit calculation.

This module turns an SMC analysis into concrete, broker-ready price levels. It
is the *only* place trade prices are produced, and it is fully deterministic:
the language model is never involved here. Every target must be supported by
real structure and sit on the profitable side of the entry, or the setup is
rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import floor
from typing import Literal, Sequence

from .smc.levels import Level, resistances_above, supports_below
from .smc.zones import Zone

NSE_TICK = 0.05


class EntryModel(str, Enum):
    NORMAL = "normal"            # trade near current executable price
    CONSERVATIVE = "conservative"  # wait for retrace into the zone
    AGGRESSIVE = "aggressive"    # anticipate (limit) entry; disabled by default


class LevelError(str, Enum):
    NONE = "none"
    NO_ZONE = "no_zone"
    PRICE_TOO_FAR = "price_too_far"
    INVALID_STOP = "invalid_stop"
    RISK_TOO_HIGH = "risk_too_high"
    INSUFFICIENT_TARGETS = "insufficient_targets"
    LOW_RR = "low_reward_risk"


@dataclass(frozen=True)
class TradeLevels:
    direction: Literal["buy", "sell"]
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    risk_per_share: float
    reward_risk_tp1: float
    reward_risk_final: float
    entry_model: EntryModel
    ok: bool
    error: LevelError = LevelError.NONE


def round_to_tick(price: float, tick: float = NSE_TICK) -> float:
    """Round to the nearest tradable tick (NSE default 0.05)."""
    if tick <= 0:
        return round(price, 2)
    return round(round(price / tick) * tick, 2)


@dataclass
class LevelConfig:
    entry_model: EntryModel = EntryModel.NORMAL
    stop_buffer_pct: float = 0.25          # buffer beyond structural invalidation
    max_entry_deviation_pct: float = 1.5   # reject if price has run past entry
    min_reward_risk: float = 2.0           # minimum gross R:R on the final target
    max_risk_pct: float = 8.0              # reject if stop distance is huge
    cost_pct: float = 0.2                  # round-trip estimated cost as % of price
    tick: float = NSE_TICK


def compute_levels(
    direction: Literal["buy", "sell"],
    current_price: float,
    zone: Zone | None,
    levels: Sequence[Level],
    swing_stop: float | None,
    config: LevelConfig,
) -> TradeLevels:
    """Compute a full trade template or an explicit rejection.

    ``swing_stop`` is a structural stop candidate (swing low for buys, swing high
    for sells) used when no zone boundary is available or when it is tighter/safer.
    """
    if zone is None and swing_stop is None:
        return _reject(direction, config.entry_model, LevelError.NO_ZONE)

    if direction == "buy":
        return _compute_buy(current_price, zone, levels, swing_stop, config)
    return _compute_sell(current_price, zone, levels, swing_stop, config)


def _compute_buy(current_price, zone, levels, swing_stop, config) -> TradeLevels:
    # Entry
    if zone is not None and config.entry_model == EntryModel.CONSERVATIVE:
        entry = round_to_tick(zone.top, config.tick)
    elif zone is not None and config.entry_model == EntryModel.AGGRESSIVE:
        entry = round_to_tick(zone.mid, config.tick)
    else:
        entry = round_to_tick(current_price, config.tick)

    # Reject if price has already run too far above a zone-based entry.
    if _deviation_pct(current_price, entry) > config.max_entry_deviation_pct and current_price > entry:
        return _reject("buy", config.entry_model, LevelError.PRICE_TOO_FAR)

    # Stop-loss: below structural invalidation, with buffer.
    structural = []
    if zone is not None:
        structural.append(zone.bottom)
    if swing_stop is not None:
        structural.append(swing_stop)
    raw_stop = min(structural)
    stop = round_to_tick(raw_stop * (1 - config.stop_buffer_pct / 100), config.tick)
    if stop >= entry:
        return _reject("buy", config.entry_model, LevelError.INVALID_STOP)

    risk = entry - stop
    if risk / entry * 100 > config.max_risk_pct:
        return _reject("buy", config.entry_model, LevelError.RISK_TOO_HIGH)

    targets = [lvl.price for lvl in resistances_above(levels, entry)]
    return _finalize("buy", entry, stop, risk, targets, config)


def _compute_sell(current_price, zone, levels, swing_stop, config) -> TradeLevels:
    if zone is not None and config.entry_model == EntryModel.CONSERVATIVE:
        entry = round_to_tick(zone.bottom, config.tick)
    elif zone is not None and config.entry_model == EntryModel.AGGRESSIVE:
        entry = round_to_tick(zone.mid, config.tick)
    else:
        entry = round_to_tick(current_price, config.tick)

    if _deviation_pct(current_price, entry) > config.max_entry_deviation_pct and current_price < entry:
        return _reject("sell", config.entry_model, LevelError.PRICE_TOO_FAR)

    structural = []
    if zone is not None:
        structural.append(zone.top)
    if swing_stop is not None:
        structural.append(swing_stop)
    raw_stop = max(structural)
    stop = round_to_tick(raw_stop * (1 + config.stop_buffer_pct / 100), config.tick)
    if stop <= entry:
        return _reject("sell", config.entry_model, LevelError.INVALID_STOP)

    risk = stop - entry
    if risk / entry * 100 > config.max_risk_pct:
        return _reject("sell", config.entry_model, LevelError.RISK_TOO_HIGH)

    targets = [lvl.price for lvl in supports_below(levels, entry)]
    return _finalize("sell", entry, stop, risk, targets, config)


def _finalize(direction, entry, stop, risk, raw_targets, config) -> TradeLevels:
    # Keep only targets on the profitable side, ordered by distance from entry.
    if direction == "buy":
        valid = sorted({round_to_tick(t, config.tick) for t in raw_targets if t > entry})
    else:
        valid = sorted({round_to_tick(t, config.tick) for t in raw_targets if t < entry}, reverse=True)

    if len(valid) < 3:
        return _reject(direction, config.entry_model, LevelError.INSUFFICIENT_TARGETS)

    tp1, tp2, tp3 = valid[0], valid[1], valid[2]
    reward_tp1 = abs(tp1 - entry) / risk if risk else 0.0
    reward_final = abs(tp3 - entry) / risk if risk else 0.0

    if reward_final < config.min_reward_risk:
        return _reject(direction, config.entry_model, LevelError.LOW_RR)

    return TradeLevels(
        direction=direction, entry=entry, stop_loss=stop,
        tp1=tp1, tp2=tp2, tp3=tp3, risk_per_share=round(risk, 2),
        reward_risk_tp1=round(reward_tp1, 2), reward_risk_final=round(reward_final, 2),
        entry_model=config.entry_model, ok=True, error=LevelError.NONE,
    )


def _reject(direction, entry_model, error: LevelError) -> TradeLevels:
    return TradeLevels(
        direction=direction, entry=0.0, stop_loss=0.0, tp1=0.0, tp2=0.0, tp3=0.0,
        risk_per_share=0.0, reward_risk_tp1=0.0, reward_risk_final=0.0,
        entry_model=entry_model, ok=False, error=error,
    )


def _deviation_pct(a: float, b: float) -> float:
    if b == 0:
        return float("inf")
    return abs(a - b) / b * 100
