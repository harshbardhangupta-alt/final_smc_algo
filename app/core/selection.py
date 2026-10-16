"""Deterministic quality-score engine (0..100) and eligibility gating.

The score is a transparent weighted sum of component factors in [0, 1]. Missing
data contributes **zero** — never positive points. Mandatory exclusion rules are
applied *before* the score matters, so a high score can never override a hard
risk gate (critical news, stale data, no valid trade levels, failed sizing).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# Component weights (sum to 100) — configurable via the Settings model.
DEFAULT_WEIGHTS: dict[str, float] = {
    "htf_alignment": 15.0,
    "market_structure": 15.0,
    "supply_demand": 15.0,
    "displacement_fvg": 10.0,
    "liquidity": 10.0,
    "sr_confluence": 10.0,
    "entry_confirmation": 10.0,
    "reward_risk": 10.0,
    "data_quality": 5.0,
}


class Verdict(str, Enum):
    PREMIUM = "premium"
    QUALIFIED = "qualified"
    WATCHLIST = "watchlist"
    REJECT = "reject"


@dataclass
class ScoreThresholds:
    premium: float = 85.0
    qualified: float = 75.0
    watchlist: float = 65.0


@dataclass
class ScoreInput:
    """Component factors in [0, 1], each produced deterministically upstream."""

    htf_alignment: float = 0.0
    market_structure: float = 0.0
    supply_demand: float = 0.0
    displacement_fvg: float = 0.0
    liquidity: float = 0.0
    sr_confluence: float = 0.0
    entry_confirmation: float = 0.0
    reward_risk: float = 0.0
    data_quality: float = 0.0


@dataclass
class Exclusions:
    """Mandatory hard gates. Any True forces REJECT regardless of score."""

    stale_data: bool = False
    no_valid_levels: bool = False
    critical_news: bool = False
    news_check_failed_fail_closed: bool = False
    sizing_failed: bool = False
    fundamental_deterioration: bool = False  # material, undermines the thesis

    def triggered(self) -> list[str]:
        return [name for name, val in self.__dict__.items() if val]


@dataclass
class ScoreResult:
    score: float
    verdict: Verdict
    breakdown: dict[str, float]
    excluded: bool
    exclusion_reasons: list[str] = field(default_factory=list)

    @property
    def is_selected(self) -> bool:
        """Only premium/qualified candidates are published as final trades."""
        return not self.excluded and self.verdict in (Verdict.PREMIUM, Verdict.QUALIFIED)


def compute_score(
    components: ScoreInput,
    exclusions: Exclusions,
    weights: dict[str, float] | None = None,
    thresholds: ScoreThresholds | None = None,
) -> ScoreResult:
    weights = weights or DEFAULT_WEIGHTS
    thresholds = thresholds or ScoreThresholds()

    breakdown: dict[str, float] = {}
    for name, weight in weights.items():
        factor = _clamp(getattr(components, name, 0.0))
        breakdown[name] = round(factor * weight, 2)

    total = round(sum(breakdown.values()), 2)

    reasons = exclusions.triggered()
    if reasons:
        return ScoreResult(
            score=total, verdict=Verdict.REJECT, breakdown=breakdown,
            excluded=True, exclusion_reasons=reasons,
        )

    if total >= thresholds.premium:
        verdict = Verdict.PREMIUM
    elif total >= thresholds.qualified:
        verdict = Verdict.QUALIFIED
    elif total >= thresholds.watchlist:
        verdict = Verdict.WATCHLIST
    else:
        verdict = Verdict.REJECT

    return ScoreResult(total, verdict, breakdown, excluded=False)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
