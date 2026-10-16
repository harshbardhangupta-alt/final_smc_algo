"""Dhan (DhanHQ v2) broker + market-data client.

IMPORTANT: Endpoint paths and payload shapes below follow DhanHQ's published v2
REST conventions, but they MUST be verified against the current official
documentation (https://dhanhq.co/docs/v2/) for your account before live use.
Capabilities differ by account permissions. We never assume an endpoint exists
without it being configured, and we never invent prices.

The client implements client-side rate limiting, bounded retries with
exponential backoff, timeouts, a health check and clear error reporting. When
credentials are absent the client runs in OFFLINE mode and raises
:class:`ProviderUnavailable` for any network call.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx

from ..config import Config, get_config
from . import ProviderDataError, ProviderUnavailable

log = logging.getLogger(__name__)


class _RateLimiter:
    """Simple thread-safe minimum-interval limiter (requests per second)."""

    def __init__(self, rps: float) -> None:
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


class DhanClient:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()
        self._limiter = _RateLimiter(self.config.dhan_rate_limit_rps)
        self._client: httpx.Client | None = None

    # -- lifecycle ----------------------------------------------------------
    @property
    def configured(self) -> bool:
        return self.config.dhan_configured

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.dhan_api_base,
                timeout=httpx.Timeout(20.0, connect=10.0),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    # DhanHQ v2 auth headers — verify names against current docs.
                    "access-token": self.config.dhan_access_token,
                    "client-id": self.config.dhan_client_id,
                },
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # -- core request with retry/backoff ------------------------------------
    def _request(self, method: str, path: str, *, json: dict | None = None,
                 retries: int = 3) -> Any:
        if not self.configured:
            raise ProviderUnavailable("Dhan API not configured (offline mode)")
        last_exc: Exception | None = None
        for attempt in range(retries):
            self._limiter.acquire()
            try:
                resp = self._http().request(method, path, json=json)
                if resp.status_code == 429:  # rate limited by broker
                    raise httpx.HTTPStatusError("rate limited", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                backoff = 2 ** attempt
                log.warning("Dhan %s %s failed (attempt %d/%d): %s; backoff %ss",
                            method, path, attempt + 1, retries, exc, backoff)
                time.sleep(backoff)
        raise ProviderDataError(f"Dhan request failed after retries: {last_exc}")

    # -- health -------------------------------------------------------------
    def health_check(self) -> dict:
        if not self.configured:
            return {"ok": False, "offline": True, "detail": "credentials not set"}
        try:
            # Fund limit / profile is a light authenticated call. Verify path.
            self._request("GET", "/fundlimit", retries=1)
            return {"ok": True, "offline": False}
        except ProviderUnavailable as exc:
            return {"ok": False, "offline": True, "detail": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "offline": False, "detail": str(exc)}

    # -- market data --------------------------------------------------------
    def historical(self, security_id: str, segment: str, interval: str,
                   from_date: str, to_date: str) -> list[dict]:
        """Daily / interval OHLCV. Returns normalised candle rows.

        ``interval`` e.g. "D" (daily) via /charts/historical or minutes via
        /charts/intraday. Verify request/response schema against current docs.
        """
        is_daily = interval.upper() in ("D", "1D", "DAY", "WEEK", "W")
        path = "/charts/historical" if is_daily else "/charts/intraday"
        payload = {
            "securityId": security_id,
            "exchangeSegment": segment,
            "instrument": "EQUITY",
            "fromDate": from_date,
            "toDate": to_date,
        }
        if not is_daily:
            payload["interval"] = interval
        data = self._request("POST", path, json=payload)
        return _normalise_candles(data)

    def ltp(self, instruments: dict[str, list[str]]) -> dict:
        """Last traded price for a set of instruments.

        ``instruments`` maps exchange-segment -> list of security ids, matching
        the DhanHQ marketfeed LTP request shape. Verify against current docs.
        """
        data = self._request("POST", "/marketfeed/ltp", json=instruments)
        return data

    # -- orders -------------------------------------------------------------
    def place_order(self, payload: dict) -> dict:
        return self._request("POST", "/orders", json=payload)

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/orders/{order_id}")

    def list_orders(self) -> list[dict]:
        data = self._request("GET", "/orders")
        return data if isinstance(data, list) else data.get("data", [])

    def cancel_order(self, order_id: str) -> dict:
        return self._request("DELETE", f"/orders/{order_id}")

    def positions(self) -> list[dict]:
        data = self._request("GET", "/positions")
        return data if isinstance(data, list) else data.get("data", [])

    def holdings(self) -> list[dict]:
        data = self._request("GET", "/holdings")
        return data if isinstance(data, list) else data.get("data", [])


def _normalise_candles(data: Any) -> list[dict]:
    """Convert DhanHQ chart response into candle rows.

    DhanHQ historical responses commonly return parallel arrays
    (open/high/low/close/volume/timestamp). We defensively support both the
    array form and a list-of-dicts form, and reject anything malformed.
    """
    if data is None:
        raise ProviderDataError("empty chart response")

    # Parallel-array form.
    if isinstance(data, dict) and "close" in data:
        o, h, l, c = data.get("open"), data.get("high"), data.get("low"), data.get("close")
        v = data.get("volume") or [0] * len(c or [])
        t = data.get("timestamp") or data.get("start_Time") or []
        if not (o and h and l and c and t) or not (len(o) == len(h) == len(l) == len(c) == len(t)):
            raise ProviderDataError("malformed array chart response")
        rows = []
        for i in range(len(c)):
            rows.append({
                "timestamp": _parse_ts(t[i]),
                "open": o[i], "high": h[i], "low": l[i], "close": c[i],
                "volume": v[i] if i < len(v) else 0,
            })
        return rows

    # List-of-dicts form.
    if isinstance(data, list):
        rows = []
        for row in data:
            rows.append({
                "timestamp": _parse_ts(row.get("timestamp") or row.get("time")),
                "open": row["open"], "high": row["high"], "low": row["low"],
                "close": row["close"], "volume": row.get("volume", 0),
            })
        return rows

    raise ProviderDataError("unrecognised chart response shape")


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
    raise ProviderDataError(f"unparseable timestamp: {value!r}")
