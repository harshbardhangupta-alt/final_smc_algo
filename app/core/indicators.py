"""Lightweight technical indicators used by the SMC engine.

Only what the deterministic engine actually needs: ATR (for displacement and
stop buffers), average traded value and simple volume stats (for the liquidity
filter). These are pure functions over :class:`Candle` sequences.
"""

from __future__ import annotations

from statistics import mean
from typing import Sequence

from .candles import Candle


def true_range(prev_close: float, candle: Candle) -> float:
    return max(
        candle.high - candle.low,
        abs(candle.high - prev_close),
        abs(candle.low - prev_close),
    )


def atr(candles: Sequence[Candle], period: int = 14) -> float:
    """Average True Range over the last ``period`` candles.

    Returns 0.0 if there are not enough candles to compute even one TR value.
    """
    if len(candles) < 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(candles)):
        trs.append(true_range(candles[i - 1].close, candles[i]))
    window = trs[-period:] if len(trs) >= period else trs
    return mean(window) if window else 0.0


def average_volume(candles: Sequence[Candle], period: int = 20) -> float:
    if not candles:
        return 0.0
    window = candles[-period:]
    return mean(c.volume for c in window)


def average_traded_value(candles: Sequence[Candle], period: int = 20) -> float:
    """Approximate average traded value = avg(close * volume) over ``period``.

    Used by the liquidity filter to exclude thinly traded securities.
    """
    if not candles:
        return 0.0
    window = candles[-period:]
    return mean(c.close * c.volume for c in window)


def recent_body_atr_ratio(candles: Sequence[Candle], lookback: int = 20) -> float:
    """Median body size relative to ATR — a crude displacement baseline."""
    a = atr(candles)
    if a <= 0 or len(candles) < 2:
        return 0.0
    window = candles[-lookback:]
    bodies = sorted(c.body for c in window)
    median = bodies[len(bodies) // 2]
    return median / a
