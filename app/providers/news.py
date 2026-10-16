"""News retrieval pipeline.

Fetches recent news for a symbol from a licensed news API when configured.
Returns items with headline, source, published timestamp, url and relevance.
De-duplicates and drops stale articles. When no provider is configured the
result is marked ``ok=False`` so the caller applies the fail-closed policy —
we never fabricate headlines.

Respect each provider's terms, licensing and rate limits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from ..config import Config, get_config

log = logging.getLogger(__name__)


@dataclass
class NewsItem:
    headline: str
    source: str
    published_at: datetime | None
    url: str
    def to_dict(self) -> dict:
        return {
            "headline": self.headline, "source": self.source,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "url": self.url,
        }


@dataclass
class NewsResult:
    ok: bool
    items: list[NewsItem] = field(default_factory=list)
    checked_at: datetime | None = None
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "error": self.error,
            "items": [i.to_dict() for i in self.items],
            "count": len(self.items),
        }


class NewsProvider:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()

    @property
    def configured(self) -> bool:
        return self.config.news_configured

    def fetch(self, symbol: str, company_name: str = "", max_age_days: int = 14) -> NewsResult:
        now = datetime.now(timezone.utc)
        if not self.configured:
            return NewsResult(ok=False, checked_at=now, error="news provider not configured")
        query = company_name or symbol
        try:
            items = self._query_newsapi(query, max_age_days)
        except Exception as exc:  # noqa: BLE001
            log.warning("News fetch failed for %s: %s", symbol, exc)
            return NewsResult(ok=False, checked_at=now, error=f"fetch failed: {exc}")
        return NewsResult(ok=True, items=_dedupe(items), checked_at=now)

    def _query_newsapi(self, query: str, max_age_days: int) -> list[NewsItem]:
        since = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).date().isoformat()
        params = {
            "q": query, "from": since, "language": "en",
            "sortBy": "publishedAt", "pageSize": 20, "apiKey": self.config.news_api_key,
        }
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(f"{self.config.news_api_base}/everything", params=params)
            resp.raise_for_status()
            data = resp.json()
        items: list[NewsItem] = []
        for a in data.get("articles", []):
            items.append(NewsItem(
                headline=a.get("title", ""),
                source=(a.get("source") or {}).get("name", ""),
                published_at=_parse(a.get("publishedAt")),
                url=a.get("url", ""),
            ))
        return items


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    out: list[NewsItem] = []
    for it in items:
        key = it.headline.strip().lower()[:120]
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out
