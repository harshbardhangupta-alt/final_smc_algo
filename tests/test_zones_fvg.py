"""Supply/demand zone and FVG tests, incl. invalidation and fill tracking."""

from datetime import datetime, timedelta, timezone

from app.core.candles import Candle
from app.core.smc.fvg import detect_fvgs
from app.core.smc.zones import best_zone, detect_zones
from tests.conftest import make_candles

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _c(i, o, h, l, cl, v=1_000_000):
    return Candle(BASE + timedelta(days=i), o, h, l, cl, v)


def test_demand_zone_detected_before_displacement():
    # Flat base, then a strong bullish displacement candle.
    candles = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 101, 99, 100),      # base candle
        _c(2, 100, 112, 100, 111),     # displacement up
        _c(3, 111, 113, 109, 112),
    ]
    zones = detect_zones(candles, min_displacement_atr=1.0)
    demand = [z for z in zones if z.kind == "demand"]
    assert demand, "expected a demand zone before the up-move"
    z = demand[0]
    assert z.bottom <= 100 <= z.top + 1


def test_zone_invalidated_when_price_closes_through():
    candles = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 101, 99, 100),
        _c(2, 100, 112, 100, 111),     # demand created ~ base low 99
        _c(3, 108, 109, 95, 96),       # closes below invalidation (base low) -> invalidated
    ]
    zones = detect_zones(candles, min_displacement_atr=1.0)
    demand = [z for z in zones if z.kind == "demand"]
    assert demand and demand[0].invalidated is True


def test_best_zone_prefers_fresh_unmitigated():
    candles = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 101, 99, 100),
        _c(2, 100, 112, 100, 111),
        _c(3, 111, 113, 110, 112),
    ]
    zones = detect_zones(candles, min_displacement_atr=1.0)
    chosen = best_zone(zones, "demand", reference_price=112)
    assert chosen is not None and chosen.kind == "demand"


def test_bullish_fvg_detected_and_fill_tracked():
    # 3-candle bullish FVG: candle0.high < candle2.low, big middle body.
    candles = [
        _c(0, 100, 101, 99, 100),      # small
        _c(1, 100, 119, 100, 118),     # strong displacement candle
        _c(2, 104, 106, 103, 105),     # small; low 103 > candle0 high 101 => gap 101..103
        _c(3, 105, 106, 102, 104),     # dips to 102 into the gap -> partial fill
    ]
    fvgs = detect_fvgs(candles, min_displacement_atr=1.0)
    bull = [g for g in fvgs if g.direction == "bullish"]
    assert bull, "expected a bullish FVG"
    g = bull[0]
    assert g.top > g.bottom
    assert 0.0 <= g.fill_percent <= 1.0


def test_no_fvg_without_displacement():
    candles = make_candles([100, 100.5, 101, 101.5, 102], wick=0.2)
    # Small bodies => below displacement threshold => no qualifying FVGs.
    assert detect_fvgs(candles, min_displacement_atr=1.5) == []
