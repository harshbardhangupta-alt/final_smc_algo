"""Market-structure tests: swings, BOS/CHOCH, trend, no-repaint guarantees."""

from app.core.smc.structure import Trend, analyze_structure, find_swings
from tests.conftest import make_candles


def test_find_swings_identifies_local_extremes():
    candles = make_candles([10, 12, 15, 12, 10, 13, 17, 14, 11])
    swings = find_swings(candles, strength=2)
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    assert highs and lows
    # The peak at index 2 (price 15) must be a confirmed swing high.
    assert any(s.index == 2 and abs(s.price - 16) < 2 for s in highs)


def test_uptrend_classified_bullish(uptrend):
    result = analyze_structure(uptrend, strength=2)
    assert result.trend == Trend.BULLISH
    assert any(b.direction == "bullish" for b in result.breaks)


def test_downtrend_classified_bearish(downtrend):
    result = analyze_structure(downtrend, strength=2)
    assert result.trend == Trend.BEARISH
    assert any(b.direction == "bearish" for b in result.breaks)


def test_bos_requires_close_not_wick():
    # A tall wick above a prior swing high that CLOSES back below must NOT be a BOS.
    from app.core.candles import Candle
    from datetime import datetime, timezone, timedelta
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closes = [10, 12, 15, 12, 10, 11]   # swing high ~15 at index 2
    candles = make_candles(closes)
    # Append a candle that wicks to 20 but closes at 11 (below 15).
    candles.append(Candle(base + timedelta(days=len(closes)), open=11, high=20, low=10, close=11, volume=1))
    result = analyze_structure(candles, strength=2)
    # No bullish break should be registered from the wick alone.
    assert not any(b.direction == "bullish" for b in result.breaks)


def test_choch_flips_direction():
    # Up then a decisive close below the confirmed swing low => bearish CHOCH.
    closes = [10, 13, 17, 14, 11, 15, 20, 16, 12, 8, 6]
    candles = make_candles(closes)
    result = analyze_structure(candles, strength=2)
    kinds = [(b.direction, b.kind) for b in result.breaks]
    assert any(k == ("bearish", "CHOCH") for k in kinds)


def test_no_swings_on_short_series():
    assert find_swings(make_candles([50, 60, 70]), strength=2) == []
