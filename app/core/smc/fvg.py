"""Displacement detection and Fair Value Gaps (FVG).

A bullish FVG is a 3-candle pattern where candle[i-1].high < candle[i+1].low,
leaving an unfilled gap. The bearish mirror uses candle[i-1].low > candle[i+1].high.
The middle candle must show *displacement* (body large relative to ATR) so we do
not treat every gap as institutional activity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

from ..candles import Candle
from ..indicators import atr


@dataclass(frozen=True)
class FairValueGap:
    index: int
    ts: datetime
    direction: Literal["bullish", "bearish"]
    top: float
    bottom: float
    size: float
    displacement_ratio: float  # middle-candle body / ATR
    fill_percent: float        # 0..1 how much of the gap later price has filled

    @property
    def is_filled(self) -> bool:
        return self.fill_percent >= 1.0


def detect_fvgs(
    candles: Sequence[Candle],
    min_displacement_atr: float = 1.2,
    period: int = 14,
) -> list[FairValueGap]:
    """Detect qualifying FVGs across the series.

    ``min_displacement_atr`` is the minimum middle-candle body / ATR ratio for a
    gap to qualify, keeping only displacement-driven gaps.
    """
    gaps: list[FairValueGap] = []
    n = len(candles)
    if n < 3:
        return gaps
    a = atr(candles, period=period)
    if a <= 0:
        return gaps

    for i in range(1, n - 1):
        prev_c, mid, next_c = candles[i - 1], candles[i], candles[i + 1]
        disp = mid.body / a
        if disp < min_displacement_atr:
            continue
        if prev_c.high < next_c.low:  # bullish gap
            bottom, top = prev_c.high, next_c.low
            gaps.append(
                _build(i, mid.ts, "bullish", top, bottom, disp, candles[i + 2:])
            )
        elif prev_c.low > next_c.high:  # bearish gap
            bottom, top = next_c.high, prev_c.low
            gaps.append(
                _build(i, mid.ts, "bearish", top, bottom, disp, candles[i + 2:])
            )
    return gaps


def _build(
    index: int,
    ts: datetime,
    direction: str,
    top: float,
    bottom: float,
    disp: float,
    future: Sequence[Candle],
) -> FairValueGap:
    size = top - bottom
    fill = _fill_percent(direction, top, bottom, future)
    return FairValueGap(index, ts, direction, top, bottom, size, disp, fill)  # type: ignore[arg-type]


def _fill_percent(
    direction: str, top: float, bottom: float, future: Sequence[Candle]
) -> float:
    """How much of the gap subsequent candles have retraced into (0..1)."""
    size = top - bottom
    if size <= 0:
        return 1.0
    deepest = 0.0
    for c in future:
        if direction == "bullish":
            # Price trading back down into the gap fills it from the top.
            penetration = top - max(c.low, bottom)
        else:
            penetration = min(c.high, top) - bottom
        deepest = max(deepest, penetration)
    return max(0.0, min(1.0, deepest / size))
