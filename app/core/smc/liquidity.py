"""Liquidity analysis: equal highs/lows, pools and sweeps.

We *infer* liquidity from historical price only. We never claim access to hidden
institutional orders. A sweep requires a wick beyond a prior swing followed by a
close back on the other side (sweep-and-reclaim), not just a wick crossing a
level, as the strategy rules demand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

from ..candles import Candle
from ..indicators import atr
from .structure import Swing


@dataclass(frozen=True)
class LiquidityPool:
    price: float
    side: Literal["buy", "sell"]  # buy-side = resting above highs, sell-side below lows
    touches: int
    equal: bool                   # part of an equal-highs / equal-lows cluster


@dataclass(frozen=True)
class LiquiditySweep:
    index: int
    ts: datetime
    side: Literal["buy", "sell"]
    swept_level: float
    reclaimed: bool


def find_equal_levels(
    swings: Sequence[Swing], tolerance_pct: float = 0.1
) -> list[LiquidityPool]:
    """Cluster swing highs/lows that sit within ``tolerance_pct`` of each other."""
    pools: list[LiquidityPool] = []
    for kind, side in (("high", "buy"), ("low", "sell")):
        pts = sorted((s.price for s in swings if s.kind == kind))
        i = 0
        while i < len(pts):
            cluster = [pts[i]]
            j = i + 1
            while j < len(pts) and abs(pts[j] - cluster[0]) / cluster[0] * 100 <= tolerance_pct:
                cluster.append(pts[j])
                j += 1
            level = sum(cluster) / len(cluster)
            pools.append(
                LiquidityPool(
                    price=level, side=side, touches=len(cluster),  # type: ignore[arg-type]
                    equal=len(cluster) >= 2,
                )
            )
            i = j
    return pools


def detect_sweeps(
    candles: Sequence[Candle],
    swings: Sequence[Swing],
    period: int = 14,
) -> list[LiquiditySweep]:
    """Detect sweep-and-reclaim events against confirmed swing levels."""
    sweeps: list[LiquiditySweep] = []
    if not swings:
        return sweeps
    a = atr(candles, period=period)
    tol = max(a * 0.05, 1e-9)

    for i, c in enumerate(candles):
        for s in swings:
            if s.index >= i:
                continue  # only prior confirmed swings can be swept
            if s.kind == "high" and c.high > s.price + tol:
                reclaimed = c.close < s.price
                sweeps.append(LiquiditySweep(i, c.ts, "buy", s.price, reclaimed))
            elif s.kind == "low" and c.low < s.price - tol:
                reclaimed = c.close > s.price
                sweeps.append(LiquiditySweep(i, c.ts, "sell", s.price, reclaimed))
    return sweeps


def recent_reclaim(
    sweeps: Sequence[LiquiditySweep], side: str, within: int, last_index: int
) -> bool:
    """True if a reclaimed sweep of ``side`` happened within the last N candles."""
    for s in sweeps:
        if s.side == side and s.reclaimed and last_index - s.index <= within:
            return True
    return False
