"""Market structure: swing points, BOS, CHOCH and trend.

Swings are detected with a symmetric fractal rule (a swing high is strictly the
highest high within ``strength`` candles on each side). Structure breaks require
a candle *close* beyond the most recent confirmed swing, never just a wick — as
mandated by the strategy rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal, Sequence

from ..candles import Candle


class Trend(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGE = "range"


@dataclass(frozen=True)
class Swing:
    index: int
    ts: datetime
    price: float
    kind: Literal["high", "low"]


@dataclass(frozen=True)
class StructureBreak:
    index: int
    ts: datetime
    price: float
    direction: Literal["bullish", "bearish"]
    kind: Literal["BOS", "CHOCH"]
    broken_swing_price: float


@dataclass(frozen=True)
class StructureResult:
    swings: list[Swing]
    breaks: list[StructureBreak]
    trend: Trend
    last_swing_high: Swing | None
    last_swing_low: Swing | None


def find_swings(candles: Sequence[Candle], strength: int = 2) -> list[Swing]:
    """Return confirmed fractal swing highs/lows.

    A candle at index ``i`` is a swing high when its high is strictly greater
    than the highs of the ``strength`` candles on both sides. Swing lows are the
    mirror. The ``strength`` candles on each edge can never be swings, which is
    what makes every returned swing *confirmed* (no look-ahead risk).
    """
    swings: list[Swing] = []
    n = len(candles)
    if n < 2 * strength + 1:
        return swings
    for i in range(strength, n - strength):
        c = candles[i]
        left = candles[i - strength:i]
        right = candles[i + 1:i + 1 + strength]
        if all(c.high > x.high for x in left) and all(c.high > x.high for x in right):
            swings.append(Swing(index=i, ts=c.ts, price=c.high, kind="high"))
        # A candle can be both (rare); evaluate low independently.
        if all(c.low < x.low for x in left) and all(c.low < x.low for x in right):
            swings.append(Swing(index=i, ts=c.ts, price=c.low, kind="low"))
    swings.sort(key=lambda s: (s.index, 0 if s.kind == "high" else 1))
    return swings


def analyze_structure(candles: Sequence[Candle], strength: int = 2) -> StructureResult:
    """Detect swings, structure breaks (BOS/CHOCH) and classify the trend.

    The algorithm walks forward candle-by-candle. It tracks the most recent
    confirmed swing high and swing low (a swing is only "confirmed" once the
    ``strength`` candles to its right exist). A close above the reference swing
    high is a bullish break; a close below the reference swing low is bearish.
    The first break that flips the prevailing direction is a CHOCH; subsequent
    breaks in the same direction are BOS.
    """
    swings = find_swings(candles, strength=strength)
    result_breaks: list[StructureBreak] = []

    # Index -> list of swings confirmed as of that candle index.
    swings_by_confirm: dict[int, list[Swing]] = {}
    for s in swings:
        confirm_idx = s.index + strength  # right-side candles needed
        swings_by_confirm.setdefault(confirm_idx, []).append(s)

    ref_high: Swing | None = None
    ref_low: Swing | None = None
    direction: Literal["bullish", "bearish"] | None = None

    for i, c in enumerate(candles):
        for s in swings_by_confirm.get(i, []):
            if s.kind == "high":
                ref_high = s
            else:
                ref_low = s

        if ref_high is not None and c.close > ref_high.price:
            kind = "CHOCH" if direction == "bearish" else "BOS"
            result_breaks.append(
                StructureBreak(i, c.ts, c.close, "bullish", kind, ref_high.price)
            )
            direction = "bullish"
            ref_high = None  # require a new confirmed high before the next break
        elif ref_low is not None and c.close < ref_low.price:
            kind = "CHOCH" if direction == "bullish" else "BOS"
            result_breaks.append(
                StructureBreak(i, c.ts, c.close, "bearish", kind, ref_low.price)
            )
            direction = "bearish"
            ref_low = None

    trend = _classify_trend(direction, swings)
    last_high = next((s for s in reversed(swings) if s.kind == "high"), None)
    last_low = next((s for s in reversed(swings) if s.kind == "low"), None)
    return StructureResult(swings, result_breaks, trend, last_high, last_low)


def _classify_trend(
    direction: Literal["bullish", "bearish"] | None,
    swings: Sequence[Swing],
) -> Trend:
    if direction == "bullish":
        return Trend.BULLISH
    if direction == "bearish":
        return Trend.BEARISH
    # No confirmed break yet: fall back to swing geometry if available.
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1].price > highs[-2].price and lows[-1].price > lows[-2].price:
            return Trend.BULLISH
        if highs[-1].price < highs[-2].price and lows[-1].price < lows[-2].price:
            return Trend.BEARISH
    return Trend.RANGE
