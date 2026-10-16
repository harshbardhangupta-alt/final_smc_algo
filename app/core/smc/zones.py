"""Supply & demand zones.

A demand zone is the base candle (or last down/neutral candle) immediately
preceding a bullish displacement move; a supply zone precedes a bearish
displacement. Each zone records boundaries, creation time, freshness, retests,
mitigation status and its invalidation level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Sequence

from ..candles import Candle
from ..indicators import atr


@dataclass
class Zone:
    index: int
    ts: datetime
    kind: Literal["demand", "supply"]
    top: float
    bottom: float
    timeframe: str
    displacement_ratio: float
    retests: int = 0
    mitigated: bool = False
    invalidated: bool = False
    invalidation_level: float = field(default=0.0)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def height(self) -> float:
        return self.top - self.bottom

    @property
    def is_fresh(self) -> bool:
        return self.retests == 0 and not self.mitigated and not self.invalidated


def detect_zones(
    candles: Sequence[Candle],
    timeframe: str = "1D",
    min_displacement_atr: float = 1.3,
    period: int = 14,
) -> list[Zone]:
    """Detect demand/supply zones and update their state against later price."""
    zones: list[Zone] = []
    n = len(candles)
    if n < 3:
        return zones
    a = atr(candles, period=period)
    if a <= 0:
        return zones

    for i in range(1, n - 1):
        base = candles[i - 1]
        move = candles[i]
        disp = move.body / a
        if disp < min_displacement_atr:
            continue
        if move.is_bullish and move.close > base.high:
            # Demand zone = body/range of the base candle before the up-move.
            top = max(base.open, base.close)
            bottom = base.low
            z = Zone(
                index=i - 1, ts=base.ts, kind="demand", top=top, bottom=bottom,
                timeframe=timeframe, displacement_ratio=disp,
                invalidation_level=base.low,
            )
            _update_zone_state(z, candles[i + 1:])
            zones.append(z)
        elif move.is_bearish and move.close < base.low:
            bottom = min(base.open, base.close)
            top = base.high
            z = Zone(
                index=i - 1, ts=base.ts, kind="supply", top=top, bottom=bottom,
                timeframe=timeframe, displacement_ratio=disp,
                invalidation_level=base.high,
            )
            _update_zone_state(z, candles[i + 1:])
            zones.append(z)
    return zones


def _update_zone_state(zone: Zone, future: Sequence[Candle]) -> None:
    """Count retests and set mitigation / invalidation from later candles."""
    touched = False
    for c in future:
        overlaps = c.low <= zone.top and c.high >= zone.bottom
        if overlaps:
            if not touched:
                touched = True
            zone.retests += 1
            zone.mitigated = True
        if zone.kind == "demand" and c.close < zone.invalidation_level:
            zone.invalidated = True
            break
        if zone.kind == "supply" and c.close > zone.invalidation_level:
            zone.invalidated = True
            break


def best_zone(
    zones: Sequence[Zone], kind: str, reference_price: float
) -> Zone | None:
    """Pick the most relevant un-invalidated zone of ``kind``.

    Prefers fresh, un-mitigated zones; for demand it must sit below the
    reference price, for supply above it (so it can still act as an entry).
    Ties break towards the nearest zone and the stronger displacement.
    """
    candidates = [z for z in zones if z.kind == kind and not z.invalidated]
    if kind == "demand":
        candidates = [z for z in candidates if z.top <= reference_price]
    else:
        candidates = [z for z in candidates if z.bottom >= reference_price]
    if not candidates:
        return None

    def score(z: Zone) -> tuple:
        distance = abs(reference_price - z.mid)
        return (0 if z.is_fresh else 1, z.retests, distance, -z.displacement_ratio)

    return sorted(candidates, key=score)[0]
