"""Fundamental data retrieval.

Production deployments should wire a licensed fundamentals source (e.g. an
exchange data vendor or a paid API) here. We NEVER fabricate financial ratios:
when no source is configured the result is marked unavailable, and the caller
treats fundamentals as unknown (optionally watchlist-only per the policy).

The returned structure captures the figures the fundamental-analysis rules ask
for, each with its source and reporting period so provenance is auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class FundamentalData:
    ok: bool
    symbol: str
    source: str = ""
    period: str = ""
    fetched_at: datetime | None = None
    metrics: dict = field(default_factory=dict)   # revenue_growth, eps_trend, debt, etc.
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "source": self.source, "period": self.period,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "metrics": self.metrics, "error": self.error,
        }


class FundamentalsProvider:
    """Pluggable fundamentals provider.

    The default implementation has no configured source and therefore always
    reports ``ok=False``. Subclass or inject a real fetcher in production.
    """

    def __init__(self, fetcher=None) -> None:
        self._fetcher = fetcher  # optional callable(symbol) -> dict of metrics

    @property
    def configured(self) -> bool:
        return self._fetcher is not None

    def fetch(self, symbol: str) -> FundamentalData:
        now = datetime.now(timezone.utc)
        if not self.configured:
            return FundamentalData(
                ok=False, symbol=symbol, fetched_at=now,
                error="no fundamentals source configured",
            )
        try:
            payload = self._fetcher(symbol)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            return FundamentalData(ok=False, symbol=symbol, fetched_at=now, error=str(exc))
        return FundamentalData(
            ok=True, symbol=symbol, fetched_at=now,
            source=payload.get("source", "custom"),
            period=payload.get("period", ""),
            metrics=payload.get("metrics", {}),
        )
