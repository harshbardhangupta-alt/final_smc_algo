"""Scan orchestration: universe -> data -> analysis -> research -> selection.

The scanner runs the full pipeline for each eligible instrument and persists a
:class:`Signal` row per candidate (published only when qualified). It is the
single place technical, fundamental and news findings are combined into the
deterministic eligibility decision.

Data access is injected via a ``candle_fetcher`` callable so the pipeline is
fully unit-testable without network access. In offline mode (no Dhan) the
default fetcher yields no data and the scan honestly publishes nothing — it
never fabricates prices.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Sequence

from sqlalchemy.orm import Session

from ..core.analysis import AnalysisResult, analyze_symbol
from ..core.candles import Candle, build_candles, resample_weekly
from ..core.risk import PortfolioState, size_position
from ..core.selection import Exclusions, compute_score
from ..models import Instrument, ScanRun, Settings, Signal
from ..providers import ProviderUnavailable
from ..providers.dhan import DhanClient
from ..providers.fundamentals import FundamentalsProvider
from ..providers.news import NewsProvider
from ..providers.openai_client import OpenAIResearcher
from . import mappers

log = logging.getLogger(__name__)

CandleBundle = dict[str, list[Candle]]
CandleFetcher = Callable[[Instrument], CandleBundle | None]


def default_candle_fetcher(dhan: DhanClient) -> CandleFetcher:
    """Build a fetcher backed by Dhan historical data (daily + derived weekly)."""

    def fetch(inst: Instrument) -> CandleBundle | None:
        if not dhan.configured or not inst.security_id:
            return None
        to_date = datetime.now(timezone.utc).date().isoformat()
        from_date = (datetime.now(timezone.utc) - timedelta(days=500)).date().isoformat()
        rows = dhan.historical(inst.security_id, inst.segment, "D", from_date, to_date)
        daily = build_candles(rows)
        if len(daily) < 30:
            return None
        return {"D": daily, "W": resample_weekly(daily)}

    return fetch


def run_scan(
    db: Session,
    *,
    dhan: DhanClient | None = None,
    researcher: OpenAIResearcher | None = None,
    news: NewsProvider | None = None,
    fundamentals: FundamentalsProvider | None = None,
    candle_fetcher: CandleFetcher | None = None,
) -> ScanRun:
    settings = _get_settings(db)
    # Resolve credentials from DB (admin-managed) merged over the environment.
    from .credentials import resolve_config
    resolved = resolve_config(db)
    dhan = dhan or DhanClient(resolved)
    researcher = researcher or OpenAIResearcher(resolved)
    news = news or NewsProvider(resolved)
    fundamentals = fundamentals or FundamentalsProvider()
    fetch = candle_fetcher or default_candle_fetcher(dhan)

    universe_sel = (settings.universe or {}).get("selected", "NIFTY500")
    run = ScanRun(universe=universe_sel, status="running")
    db.add(run)
    db.commit()

    instruments = db.query(Instrument).filter(Instrument.active.is_(True)).all()
    analysis_cfg = mappers.analysis_config(settings.scoring, settings.universe, settings.scheduling)
    cap_cfg = mappers.capital_config(settings.capital)
    weights = (settings.scoring or {}).get("weights") or None
    thresholds = mappers.score_thresholds(settings.scoring)
    policy = settings.policy or {}
    expiry_minutes = int((settings.scheduling or {}).get("signal_expiry_minutes", 240))

    portfolio = PortfolioState()
    scanned = buy_count = sell_count = 0

    for inst in instruments:
        scanned += 1
        try:
            signal = _process_instrument(
                db, run, inst, fetch, analysis_cfg, cap_cfg, weights, thresholds,
                policy, researcher, news, fundamentals, portfolio, expiry_minutes,
            )
        except ProviderUnavailable as exc:
            log.info("Data unavailable for %s: %s", inst.symbol, exc)
            continue
        except Exception as exc:  # noqa: BLE001  (never let one symbol kill the scan)
            log.exception("Error scanning %s: %s", inst.symbol, exc)
            continue
        if signal and signal.published:
            if signal.direction == "buy":
                buy_count += 1
            else:
                sell_count += 1
            # Reserve capital so later picks respect portfolio limits.
            portfolio.open_positions += 1
            portfolio.used_cash += signal.capital_required
            portfolio.open_risk_amount += signal.risk_amount
            portfolio.gross_exposure += signal.capital_required
            sector = inst.sector or "UNKNOWN"
            portfolio.sector_exposure[sector] = (
                portfolio.sector_exposure.get(sector, 0.0) + signal.capital_required
            )

    run.scanned = scanned
    run.qualified_buy = buy_count
    run.qualified_sell = sell_count
    run.status = "completed"
    run.finished_at = datetime.now(timezone.utc)
    if not dhan.configured:
        run.message = "offline mode: Dhan not configured; no live data fetched"
    db.commit()
    log.info("Scan %d done: scanned=%d buy=%d sell=%d", run.id, scanned, buy_count, sell_count)
    return run


def _process_instrument(
    db, run, inst, fetch, analysis_cfg, cap_cfg, weights, thresholds, policy,
    researcher, news, fundamentals, portfolio, expiry_minutes,
) -> Signal | None:
    bundle = fetch(inst)
    if not bundle:
        return None

    analysis = analyze_symbol(inst.symbol, bundle, analysis_cfg)
    if analysis.direction == "none":
        return None

    # --- Research: news + fundamentals + OpenAI interpretation ----------------
    news_result = news.fetch(inst.symbol, inst.name)
    fund = fundamentals.fetch(inst.symbol)
    assessment = researcher.assess(
        inst.symbol, analysis.direction,
        {
            "news": [i.to_dict() for i in news_result.items],
            "fundamentals": fund.metrics,
            "technical_summary": {
                "trend_daily": analysis.trend_daily.value,
                "trend_weekly": analysis.trend_weekly.value,
                "direction": analysis.direction,
            },
        },
    )

    # --- Mandatory exclusions -------------------------------------------------
    exclusions = _build_exclusions(analysis, news_result, fund, assessment, policy)

    score = compute_score(analysis.components, exclusions, weights, thresholds)

    # --- Position sizing (only matters for selected candidates) ---------------
    plan = None
    if analysis.levels and analysis.levels.ok:
        plan = size_position(
            analysis.levels.entry, analysis.levels.stop_loss, cap_cfg, portfolio,
            sector=inst.sector or "UNKNOWN", product="CASH",
        )
        if not plan.ok:
            exclusions.sizing_failed = True
            score = compute_score(analysis.components, exclusions, weights, thresholds)

    published = score.is_selected and analysis.levels is not None and analysis.levels.ok
    signal = _persist_signal(
        db, run, inst, analysis, score, plan, news_result, fund, assessment,
        policy, published, expiry_minutes,
    )
    return signal


def _build_exclusions(analysis, news_result, fund, assessment, policy) -> Exclusions:
    ex = Exclusions()
    ex.stale_data = analysis.stale_data
    ex.no_valid_levels = not (analysis.levels and analysis.levels.ok)

    # News gating.
    if assessment.available:
        if assessment.critical_flag and policy.get("critical_news_action", "reject") == "reject":
            ex.critical_news = True
        if (analysis.direction == "buy" and assessment.material_negative
                and policy.get("reject_buy_on_material_negative", True)):
            ex.fundamental_deterioration = True
        if assessment.thesis_support == "undermines":
            ex.fundamental_deterioration = True
    # Fail-closed when the news/research check could not complete.
    news_ok = news_result.ok and assessment.available
    if not news_ok and policy.get("news_fail_closed", True):
        ex.news_check_failed_fail_closed = True

    # Fundamentals requirement.
    if policy.get("require_fundamentals", False) and not fund.ok:
        ex.fundamental_deterioration = True
    return ex


def _persist_signal(
    db, run, inst, analysis, score, plan, news_result, fund, assessment,
    policy, published, expiry_minutes,
) -> Signal:
    levels = analysis.levels
    now = datetime.now(timezone.utc)
    sell_type = ""
    if analysis.direction == "sell":
        # Multi-day cash shorts are not permitted on NSE; mark accordingly.
        sell_type = "analytical"  # upgraded to intraday/mtf only when enabled & eligible

    signal = Signal(
        scan_run_id=run.id,
        symbol=inst.symbol,
        direction=analysis.direction,
        product="CASH",
        sell_trade_type=sell_type,
        entry=levels.entry if levels else 0.0,
        stop_loss=levels.stop_loss if levels else 0.0,
        tp1=levels.tp1 if levels else 0.0,
        tp2=levels.tp2 if levels else 0.0,
        tp3=levels.tp3 if levels else 0.0,
        reward_risk=levels.reward_risk_final if levels else 0.0,
        quality_score=score.score,
        verdict=score.verdict.value,
        published=published,
        quantity=plan.quantity if plan else 0,
        capital_required=plan.capital_required if plan else 0.0,
        risk_amount=plan.risk_amount if plan else 0.0,
        score_breakdown=score.breakdown,
        technical={
            "trend_daily": analysis.trend_daily.value,
            "trend_weekly": analysis.trend_weekly.value,
            "zone": _zone_dict(analysis),
            "notes": analysis.notes,
            "entry_model": levels.entry_model.value if levels else None,
            "level_error": levels.error.value if levels else "no_levels",
        },
        fundamental=fund.to_dict(),
        news={
            **news_result.to_dict(),
            "assessment": {
                "available": assessment.available,
                "sentiment": assessment.sentiment,
                "confidence": assessment.confidence,
                "thesis_support": assessment.thesis_support,
                "material_negative": assessment.material_negative,
                "critical_flag": assessment.critical_flag,
                "summary": assessment.summary,
                "key_points": assessment.key_points,
                "model": assessment.model,
                "error": assessment.error,
            },
        },
        provenance={
            "latest_candle": analysis.latest_ts.isoformat() if analysis.latest_ts else None,
            "scanned_at": now.isoformat(),
            "openai_model": assessment.model,
            "news_checked_at": news_result.checked_at.isoformat() if news_result.checked_at else None,
            "fundamentals_period": fund.period,
            "config_version": 1,
        },
        rejection_reasons=score.exclusion_reasons,
        warnings=_warnings(analysis, news_result, fund, assessment),
        created_at=now,
        expires_at=now + timedelta(minutes=expiry_minutes),
    )
    db.add(signal)
    db.commit()
    return signal


def _zone_dict(analysis: AnalysisResult) -> dict | None:
    z = analysis.zone
    if not z:
        return None
    return {
        "kind": z.kind, "top": z.top, "bottom": z.bottom, "fresh": z.is_fresh,
        "retests": z.retests, "timeframe": z.timeframe,
    }


def _warnings(analysis, news_result, fund, assessment) -> list[str]:
    w: list[str] = []
    if analysis.stale_data:
        w.append("market data is stale")
    if not analysis.liquid_enough:
        w.append("below configured liquidity floor")
    if not news_result.ok:
        w.append("news check incomplete")
    if not fund.ok:
        w.append("fundamentals unavailable")
    if not assessment.available:
        w.append("AI research unavailable")
    return w


def _get_settings(db: Session) -> Settings:
    settings = db.get(Settings, 1)
    if settings is None:
        from ..settings_defaults import default_settings
        data = default_settings()
        settings = Settings(id=1, **data)
        db.add(settings)
        db.commit()
    return settings
