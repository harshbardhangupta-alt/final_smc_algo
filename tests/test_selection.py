"""Quality-score and eligibility-gating tests."""

from app.core.selection import (
    Exclusions,
    ScoreInput,
    ScoreThresholds,
    Verdict,
    compute_score,
)


def full_components() -> ScoreInput:
    return ScoreInput(
        htf_alignment=1.0, market_structure=1.0, supply_demand=1.0,
        displacement_fvg=1.0, liquidity=1.0, sr_confluence=1.0,
        entry_confirmation=1.0, reward_risk=1.0, data_quality=1.0,
    )


def test_perfect_components_score_100_premium():
    r = compute_score(full_components(), Exclusions())
    assert r.score == 100.0 and r.verdict == Verdict.PREMIUM and r.is_selected


def test_missing_data_contributes_zero():
    comps = full_components()
    comps.supply_demand = 0.0  # missing zone
    comps.liquidity = 0.0
    r = compute_score(comps, Exclusions())
    assert r.score == 75.0  # lost 15 + 10
    assert r.verdict == Verdict.QUALIFIED


def test_critical_news_forces_reject_regardless_of_score():
    r = compute_score(full_components(), Exclusions(critical_news=True))
    assert r.excluded and r.verdict == Verdict.REJECT and not r.is_selected
    assert "critical_news" in r.exclusion_reasons


def test_stale_data_excludes():
    r = compute_score(full_components(), Exclusions(stale_data=True))
    assert r.excluded and "stale_data" in r.exclusion_reasons


def test_news_fail_closed_excludes():
    r = compute_score(full_components(), Exclusions(news_check_failed_fail_closed=True))
    assert r.excluded and not r.is_selected


def test_watchlist_not_selected():
    comps = ScoreInput(
        htf_alignment=0.6, market_structure=0.6, supply_demand=0.6,
        displacement_fvg=0.5, liquidity=0.5, sr_confluence=0.5,
        entry_confirmation=0.6, reward_risk=0.6, data_quality=0.6,
    )
    r = compute_score(comps, Exclusions())
    assert r.verdict in (Verdict.WATCHLIST, Verdict.REJECT)
    assert not r.is_selected  # watchlist is never published as a final trade


def test_custom_thresholds_respected():
    comps = full_components()
    comps.htf_alignment = 0.0  # score 85
    r = compute_score(comps, Exclusions(), thresholds=ScoreThresholds(premium=90, qualified=80))
    assert r.score == 85.0 and r.verdict == Verdict.QUALIFIED
