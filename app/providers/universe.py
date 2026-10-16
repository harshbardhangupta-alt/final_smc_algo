"""NSE universe management & Dhan instrument mapping.

Provides constituent lists for the configured universe and maps each symbol to a
Dhan security id via the DhanHQ instrument master.

* A bundled **static snapshot** of NIFTY50 ships with the app so the system has
  a real, honest universe to work with offline. It is explicitly labelled a
  snapshot — production must refresh constituents from a maintained source
  (NSE indices / your data vendor).
* NIFTY100 / NIFTY500 require a refreshed constituent source; when one is not
  available we fall back to the bundled snapshot and record the limitation
  rather than inventing tickers.
* Instrument mapping is populated from the Dhan instrument master (a CSV the
  broker publishes). Symbols without a valid security id are excluded from
  live data/trading and recorded as data failures (not rejected setups).
"""

from __future__ import annotations

import csv
import io
import json
import logging
from importlib import resources
from pathlib import Path

import httpx

from sqlalchemy.orm import Session

from ..models import Instrument

log = logging.getLogger(__name__)

# Public Dhan instrument master (scrip master). Verify current URL against docs.
DHAN_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"


def load_bundled_snapshot() -> list[dict]:
    """Load the bundled NIFTY50 constituent snapshot."""
    data_path = Path(__file__).resolve().parent.parent / "data" / "nifty50.json"
    with open(data_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload.get("constituents", [])


def resolve_universe(settings_universe: dict) -> tuple[list[dict], str]:
    """Return (constituents, note) for the configured universe selection."""
    selected = (settings_universe or {}).get("selected", "NIFTY500")
    if selected == "CUSTOM":
        symbols = settings_universe.get("custom_symbols", [])
        constituents = [{"symbol": s, "name": s, "sector": "UNKNOWN"} for s in symbols]
        return constituents, "custom symbol list"

    snapshot = load_bundled_snapshot()
    if selected == "NIFTY50":
        return snapshot, "bundled NIFTY50 snapshot"
    # NIFTY100 / NIFTY500: without a refreshed constituent feed we honestly fall
    # back to the bundled snapshot and flag that it is not the full index.
    return snapshot, (
        f"{selected} requested but no refreshed constituent source configured; "
        "using bundled NIFTY50 snapshot (configure an index source for the full universe)"
    )


def sync_instruments(db: Session, constituents: list[dict]) -> dict:
    """Upsert Instrument rows for the universe and map security ids from Dhan.

    Returns a summary with counts of mapped vs. unmapped symbols. Network
    failure to fetch the scrip master is reported, not silently treated as
    rejection.
    """
    scrip_map: dict[str, dict] = {}
    scrip_error = ""
    try:
        scrip_map = _fetch_scrip_master()
    except Exception as exc:  # noqa: BLE001
        scrip_error = f"scrip master unavailable: {exc}"
        log.warning(scrip_error)

    mapped = 0
    unmapped = 0
    for c in constituents:
        symbol = c["symbol"].upper()
        inst = db.query(Instrument).filter(
            Instrument.exchange == "NSE", Instrument.symbol == symbol
        ).first()
        if inst is None:
            inst = Instrument(symbol=symbol, exchange="NSE")
            db.add(inst)
        inst.name = c.get("name", symbol)
        inst.sector = c.get("sector", "UNKNOWN")
        match = scrip_map.get(symbol)
        if match:
            inst.security_id = match["security_id"]
            inst.segment = match.get("segment", "NSE_EQ")
            inst.lot_size = match.get("lot_size", 1)
            inst.tick_size = match.get("tick_size", 0.05)
            mapped += 1
        else:
            if not inst.security_id:
                unmapped += 1
        inst.active = True
    db.commit()
    return {
        "total": len(constituents), "mapped": mapped, "unmapped": unmapped,
        "scrip_error": scrip_error,
    }


def _fetch_scrip_master() -> dict[str, dict]:
    """Download and index the Dhan scrip master by NSE equity trading symbol."""
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(DHAN_SCRIP_MASTER_URL)
        resp.raise_for_status()
        text = resp.text
    index: dict[str, dict] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        # Column names vary by scrip-master version; match defensively.
        seg = (row.get("SEM_EXM_EXCH_ID") or row.get("exchange") or "").upper()
        inst_type = (row.get("SEM_INSTRUMENT_NAME") or row.get("instrument") or "").upper()
        symbol = (row.get("SEM_TRADING_SYMBOL") or row.get("symbol") or "").upper()
        sec_id = row.get("SEM_SMST_SECURITY_ID") or row.get("security_id") or ""
        if seg != "NSE" or "EQ" not in inst_type:
            continue
        if not symbol or not sec_id:
            continue
        index[symbol] = {
            "security_id": str(sec_id),
            "segment": "NSE_EQ",
            "lot_size": int(float(row.get("SEM_LOT_UNITS", 1) or 1)),
            "tick_size": float(row.get("SEM_TICK_SIZE", 0.05) or 0.05),
        }
    return index
