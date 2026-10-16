"""Multi-timeframe SMC analysis orchestrator.

Combines structure, zones, FVGs, liquidity and S/R across timeframes into a
single directional candidate with concrete trade levels and the component
factors consumed by the scoring engine. Pure and deterministic.

Timeframes (keys): ``W`` weekly bias, ``D`` daily main setup, ``4H`` zone
confirmation, ``1H`` entry refinement (optional).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal, Sequence

from .candles import Candle, latest_close
from .indicators import atr, average_traded_value
from .selection import ScoreInput
from .smc.fvg import detect_fvgs
from .smc.levels import build_levels
from .smc.liquidity import detect_sweeps, find_equal_levels, recent_reclaim
from .smc.structure import Trend, analyze_structure
from .smc.zones import Zone, best_zone, detect_zones
from .trade_levels import LevelConfig, TradeLevels, compute_levels


@dataclass
class AnalysisConfig:
    swing_strength: int = 2
    min_displacement_atr: float = 1.3
    min_fvg_displacement_atr: float = 1.2
    min_avg_traded_value: float = 5_000_000.0  # INR liquidity floor
    staleness_days: int = 5                     # daily data older than this = stale
    level_config: LevelConfig = field(default_factory=LevelConfig)


@dataclass
class AnalysisResult:
    symbol: str
    direction: Literal["buy", "sell", "none"]
    trend_daily: Trend
    trend_weekly: Trend
    levels: TradeLevels | None
    components: ScoreInput
    zone: Zone | None
    stale_data: bool
    liquid_enough: bool
    latest_ts: datetime | None
    notes: list[str] = field(default_factory=list)


def analyze_symbol(
    symbol: str,
    candles_by_tf: dict[str, Sequence[Candle]],
    config: AnalysisConfig | None = None,
    now: datetime | None = None,
) -> AnalysisResult:
    config = config or AnalysisConfig()
    now = now or datetime.now(timezone.utc)
    notes: list[str] = []

    daily = candles_by_tf.get("D") or []
    weekly = candles_by_tf.get("W") or []
    h4 = candles_by_tf.get("4H") or []

    if len(daily) < 2 * config.swing_strength + 5:
        return _empty(symbol, notes + ["insufficient daily data"])

    price = latest_close(daily)
    latest_ts = daily[-1].ts
    stale = (now - latest_ts) > timedelta(days=config.staleness_days)
    if stale:
        notes.append("daily data stale")

    liquid = average_traded_value(daily) >= config.min_avg_traded_value
    if not liquid:
        notes.append("below liquidity floor")

    daily_struct = analyze_structure(daily, strength=config.swing_strength)
    weekly_struct = (
        analyze_structure(weekly, strength=config.swing_strength) if len(weekly) >= 2 * config.swing_strength + 1
        else None
    )
    weekly_trend = weekly_struct.trend if weekly_struct else Trend.RANGE

    direction = _decide_direction(daily_struct.trend, weekly_trend)
    if direction == "none":
        return AnalysisResult(
            symbol, "none", daily_struct.trend, weekly_trend, None,
            ScoreInput(), None, stale, liquid, latest_ts, notes + ["no directional alignment"],
        )

    zones = detect_zones(daily, "1D", config.min_displacement_atr)
    kind = "demand" if direction == "buy" else "supply"
    zone = best_zone(zones, kind, price)

    levels_list = build_levels(daily_struct.swings)
    swings = daily_struct.swings
    swing_stop = None
    if direction == "buy":
        lows = [s.price for s in swings if s.kind == "low" and s.price < price]
        swing_stop = max(lows) if lows else None
    else:
        highs = [s.price for s in swings if s.kind == "high" and s.price > price]
        swing_stop = min(highs) if highs else None

    trade_levels = compute_levels(
        direction, price, zone, levels_list, swing_stop, config.level_config
    )

    fvgs = detect_fvgs(daily, config.min_fvg_displacement_atr)
    equal_pools = find_equal_levels(swings)
    sweeps = detect_sweeps(daily, swings)

    components = _score_components(
        direction=direction,
        daily_struct=daily_struct,
        weekly_trend=weekly_trend,
        zone=zone,
        fvgs=fvgs,
        equal_pools=equal_pools,
        sweeps=sweeps,
        last_index=len(daily) - 1,
        levels=levels_list,
        price=price,
        trade_levels=trade_levels,
        liquid=liquid,
        stale=stale,
        config=config,
    )

    return AnalysisResult(
        symbol=symbol,
        direction=direction,
        trend_daily=daily_struct.trend,
        trend_weekly=weekly_trend,
        levels=trade_levels,
        components=components,
        zone=zone,
        stale_data=stale,
        liquid_enough=liquid,
        latest_ts=latest_ts,
        notes=notes,
    )


def _decide_direction(daily: Trend, weekly: Trend) -> Literal["buy", "sell", "none"]:
    """Require daily direction not to fight a decided weekly bias."""
    if daily == Trend.BULLISH and weekly in (Trend.BULLISH, Trend.RANGE):
        return "buy"
    if daily == Trend.BEARISH and weekly in (Trend.BEARISH, Trend.RANGE):
        return "sell"
    return "none"


def _score_components(
    *, direction, daily_struct, weekly_trend, zone, fvgs, equal_pools, sweeps,
    last_index, levels, price, trade_levels, liquid, stale, config,
) -> ScoreInput:
    want = "bullish" if direction == "buy" else "bearish"

    # Higher-timeframe alignment.
    htf = 1.0 if (
        (direction == "buy" and weekly_trend == Trend.BULLISH)
        or (direction == "sell" and weekly_trend == Trend.BEARISH)
    ) else 0.5 if weekly_trend == Trend.RANGE else 0.0

    # Market structure: recent confirmed break in our direction.
    dir_breaks = [b for b in daily_struct.breaks if b.direction == want]
    ms = 0.0
    if dir_breaks:
        last = dir_breaks[-1]
        recency = max(0.0, 1.0 - (last_index - last.index) / 20.0)
        ms = 0.6 + 0.4 * recency
        if last.kind == "CHOCH":
            ms = min(1.0, ms + 0.1)

    # Supply/demand zone quality & freshness.
    sd = 0.0
    if zone is not None:
        sd = 0.5
        if zone.is_fresh:
            sd += 0.3
        sd += min(0.2, max(0.0, (zone.displacement_ratio - 1.0) * 0.2))
        sd = min(1.0, sd)

    # Displacement & FVG in our direction, still partly unfilled.
    dir_fvgs = [g for g in fvgs if g.direction == want and g.fill_percent < 0.8]
    disp = 0.0
    if dir_fvgs:
        best = max(dir_fvgs, key=lambda g: g.displacement_ratio)
        disp = min(1.0, 0.5 + (best.displacement_ratio - 1.0) * 0.25 + (1 - best.fill_percent) * 0.2)

    # Liquidity evidence: equal levels + a reclaimed sweep in our favour.
    side = "sell" if direction == "buy" else "buy"  # buys reclaim sell-side sweeps
    liq = 0.0
    if any(p.equal for p in equal_pools):
        liq += 0.4
    if recent_reclaim(sweeps, side, within=10, last_index=last_index):
        liq += 0.6
    liq = min(1.0, liq)

    # S/R confluence: a structural level near our entry/zone.
    srq = 0.0
    ref = zone.mid if zone is not None else price
    for lvl in levels:
        if abs(lvl.price - ref) / ref * 100 <= 1.0:
            srq = max(srq, 0.6 + min(0.4, (lvl.touches - 1) * 0.2))
    srq = min(1.0, srq)

    # Entry confirmation: valid full trade template exists.
    entry_conf = 1.0 if trade_levels.ok else 0.0

    # Reward/risk factor scaled around the configured minimum.
    rr = 0.0
    if trade_levels.ok:
        target = config.level_config.min_reward_risk
        rr = min(1.0, trade_levels.reward_risk_final / (target * 1.5))

    # Data quality: liquid + fresh.
    dq = (0.5 if liquid else 0.0) + (0.5 if not stale else 0.0)

    return ScoreInput(
        htf_alignment=htf,
        market_structure=ms,
        supply_demand=sd,
        displacement_fvg=disp,
        liquidity=liq,
        sr_confluence=srq,
        entry_confirmation=entry_conf,
        reward_risk=rr,
        data_quality=dq,
    )


def _empty(symbol: str, notes: list[str]) -> AnalysisResult:
    return AnalysisResult(
        symbol, "none", Trend.RANGE, Trend.RANGE, None,
        ScoreInput(), None, True, False, None, notes,
    )
