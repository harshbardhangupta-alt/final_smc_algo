"""Support / resistance derived from confirmed market structure.

Targets and invalidation levels are built from *actual* structure (swing highs /
lows, repeatedly tested levels), never arbitrary percentages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from .structure import Swing


@dataclass(frozen=True)
class Level:
    price: float
    kind: Literal["support", "resistance"]
    touches: int


def build_levels(
    swings: Sequence[Swing], tolerance_pct: float = 0.35
) -> list[Level]:
    """Cluster swing highs into resistances and swing lows into supports.

    Levels tested more than once (``touches`` >= 2) are the strongest.
    """
    levels: list[Level] = []
    for kind, out_kind in (("high", "resistance"), ("low", "support")):
        pts = sorted(s.price for s in swings if s.kind == kind)
        i = 0
        while i < len(pts):
            cluster = [pts[i]]
            j = i + 1
            while j < len(pts) and abs(pts[j] - cluster[0]) / cluster[0] * 100 <= tolerance_pct:
                cluster.append(pts[j])
                j += 1
            levels.append(
                Level(
                    price=sum(cluster) / len(cluster),
                    kind=out_kind,  # type: ignore[arg-type]
                    touches=len(cluster),
                )
            )
            i = j
    return levels


def resistances_above(levels: Sequence[Level], price: float) -> list[Level]:
    out = [lvl for lvl in levels if lvl.kind == "resistance" and lvl.price > price]
    return sorted(out, key=lambda lvl: lvl.price)


def supports_below(levels: Sequence[Level], price: float) -> list[Level]:
    out = [lvl for lvl in levels if lvl.kind == "support" and lvl.price < price]
    return sorted(out, key=lambda lvl: lvl.price, reverse=True)
