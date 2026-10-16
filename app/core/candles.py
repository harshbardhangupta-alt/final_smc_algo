"""Candle data structures and timeframe helpers.

The core engine works on immutable OHLCV candles. We deliberately avoid pandas
so the engine stays light, deterministic and trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Candle:
    """A single completed OHLCV candle.

    ``ts`` is the candle *open* time as a timezone-aware UTC datetime.
    Only completed candles should ever be fed to the engine — using a forming
    candle would allow repainting, which the strategy rules forbid.
    """

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:  # pragma: no cover - cheap validation
        if self.high < self.low:
            raise ValueError(f"candle high {self.high} < low {self.low}")
        for name in ("open", "high", "low", "close"):
            if getattr(self, name) <= 0:
                raise ValueError(f"candle {name} must be positive, got {getattr(self, name)}")

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


def to_utc(ts: datetime) -> datetime:
    """Normalise any datetime to timezone-aware UTC."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def build_candles(rows: Iterable[dict]) -> list[Candle]:
    """Build a sorted candle list from provider rows.

    Each row must expose ``timestamp`` (datetime or epoch seconds) and
    ``open/high/low/close/volume``. Rows are sorted ascending by time and
    de-duplicated on timestamp (keeping the last occurrence).
    """
    by_ts: dict[datetime, Candle] = {}
    for row in rows:
        raw_ts = row["timestamp"]
        if isinstance(raw_ts, (int, float)):
            ts = datetime.fromtimestamp(raw_ts, tz=timezone.utc)
        else:
            ts = to_utc(raw_ts)
        by_ts[ts] = Candle(
            ts=ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0.0) or 0.0),
        )
    return [by_ts[k] for k in sorted(by_ts)]


def latest_close(candles: Sequence[Candle]) -> float:
    if not candles:
        raise ValueError("no candles supplied")
    return candles[-1].close


def resample_weekly(daily: Sequence[Candle]) -> list[Candle]:
    """Aggregate daily candles into ISO-week candles (Mon-Sun buckets)."""
    buckets: dict[tuple[int, int], list[Candle]] = {}
    for c in daily:
        iso = c.ts.isocalendar()
        buckets.setdefault((iso.year, iso.week), []).append(c)
    weekly: list[Candle] = []
    for key in sorted(buckets):
        group = buckets[key]
        weekly.append(Candle(
            ts=group[0].ts,
            open=group[0].open,
            high=max(c.high for c in group),
            low=min(c.low for c in group),
            close=group[-1].close,
            volume=sum(c.volume for c in group),
        ))
    return weekly
