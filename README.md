# AI-Powered NSE Stock Selection & Automated Trading System

A production-oriented Indian equity analysis and trading system. A **deterministic
Smart-Money-Concepts (SMC) engine** calculates trade levels and enforces risk rules,
**OpenAI** interprets news and fundamentals as evidence (it never invents prices),
and **Dhan (DhanHQ v2)** supplies market data and authorized execution.

The dashboard is intentionally simple: it shows only the final qualified **BUY**
and **SELL** setups with Entry, Stop-Loss, TP1/TP2/TP3 and a quality score. All the
heavy research, selection, risk management, scheduling and optional execution happen
in the backend.

> **Live auto-trading is OFF by default** and must be explicitly enabled by an
> administrator. The system never fabricates prices and, when data or news checks
> fail, it fails closed rather than presenting an unverified trade.

---

## Key properties

- **Deterministic core** (`app/core/`): candles, indicators, market structure
  (swings, BOS, CHOCH, trend), supply/demand zones, FVGs, liquidity sweeps,
  support/resistance, entry/SL/TP calculation, position sizing and a transparent
  0–100 quality score. Fully unit-tested, no network, no LLM.
- **Evidence-based AI** (`app/providers/openai_client.py`): OpenAI returns validated
  JSON classifications of news / fundamentals. Malformed or timed-out responses
  degrade to "uncertain" and the fail-closed policy applies.
- **Broker integration** (`app/providers/dhan.py`): rate limiting, retries with
  backoff, timeouts, health checks, offline mode when unconfigured.
- **Mandatory gates**: stale data, missing valid levels, critical/material negative
  news, failed news checks (fail-closed), and failed sizing all force rejection —
  a high score can never override a hard risk gate.
- **Safe execution** (`app/services/trading.py`): idempotent orders, duplicate
  prevention, partial-fill tracking, uncertain-status pausing, kill switch,
  slippage/limit checks, paper trading, Indian short-sell constraints, and explicit
  confirmation before the first live run.

## Architecture

```
app/
  core/            Deterministic engine (SMC, trade levels, risk, scoring)
    smc/           structure, zones, fvg, liquidity, levels
  providers/       dhan, openai_client, news, fundamentals, universe
  services/        scanner (orchestration), scheduler, trading, mappers
  routers/         dashboard, scan, settings, stocks, orders, health
  templates/       dashboard, detail, settings, orders (dark minimal UI)
  static/          styles.css, app.js
  models.py schemas.py config.py database.py security.py settings_defaults.py main.py
migrations/        Alembic migrations (initial schema generated)
tests/             pytest suite for all critical logic
```

Pages: **Dashboard** (final BUY/SELL), **Stock Detail**, **Settings** (universe, API
status, capital/risk, MTF, scheduling, auto-trading), **Orders & Positions**.

---

## Installation & startup — Windows (exact commands)

Open **Command Prompt** (`cmd.exe`) in the project folder.

```bat
REM 1. Create and activate a virtual environment (Python 3.11+)
python -m venv .venv
.venv\Scripts\activate

REM 2. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

REM 3. Create your environment file from the template and edit it
copy .env.example .env
notepad .env

REM 4. (Optional) apply database migrations (SQLite is created automatically otherwise)
alembic upgrade head

REM 5. Run the application
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Then open <http://127.0.0.1:8000> in your browser.

> **PowerShell** users activate with `.venv\Scripts\Activate.ps1` instead of
> `.venv\Scripts\activate`. If activation is blocked, run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then edit .env
uvicorn app.main:app --reload
```

---

## Configuration

You can supply API credentials **two ways**, and the in-app option takes precedence:

1. **From the website (recommended)** — open **Settings → API Credentials & Connections**,
   sign in as admin, and enter your **Dhan Client ID** (fixed), **Dhan Access Token**
   (rotate here whenever it expires — Dhan expires it every ~24h, no restart needed),
   **OpenAI API Key** (fixed) and optional **OpenAI model** / **News API key**. Values are
   **encrypted at rest** (Fernet, keyed from `SECRET_KEY`) and are never shown again in
   full — only a masked preview (e.g. `••••7654`). Blank fields keep the existing value, so
   rotating just the access token is one field + Save. Two **Test Connection** buttons make a
   real call to Dhan and OpenAI and report **CONNECTED / FAILED / NOT CONFIGURED**.
2. **From `.env`** — set the same keys as environment variables (see `.env.example`). Useful
   for headless/CI deployments. Any credential saved in the UI overrides the `.env` value.

Everything else an admin tunes at runtime (universe, capital/risk, scheduling, scoring,
auto-trading, news policy) also lives in the database and is edited on the **Settings** page.

Important `.env` keys (see `.env.example` for all):

| Key | Purpose |
|---|---|
| `SECRET_KEY` | Signs admin session cookies — set a long random value |
| `DATABASE_URL` | `sqlite:///./data/app.db` (dev) or `postgresql+psycopg://…` (prod) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Bootstrap admin for the control panel |
| `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN` | DhanHQ v2 credentials (blank ⇒ offline) |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | OpenAI research (blank ⇒ AI disabled) |
| `NEWS_API_KEY` | Licensed news API (blank ⇒ fail-closed on news) |

**Offline mode:** with no Dhan credentials the app runs fully — pages, settings,
scheduler — but fetches no live data and therefore publishes no signals. The
dashboard honestly shows *"No qualified trade setups currently available."* This is
by design: the system never simulates a live connection or invents prices.

> ⚠️ Verify every Dhan endpoint path, header and payload in `app/providers/dhan.py`
> and the scrip-master URL in `app/providers/universe.py` against the current
> official DhanHQ v2 documentation and your account permissions before live use.

---

## Using the system

1. **Settings → Sync Universe → Dhan IDs** maps the configured universe to Dhan
   security ids (requires network access to the Dhan scrip master).
2. **Settings → Run Scan Now**, or let the background scheduler run on its interval,
   performs the full pipeline and publishes qualified setups.
3. **Dashboard** shows the final BUY/SELL tables; click **View** for the detail page
   (why selected, risks, structure, fundamentals, provenance, warnings).
4. **Auto-trading** stays OFF until you enable it on the Settings page. Enabling
   *live* execution (paper trading off) requires `live_confirmed: true`, enforced by
   the backend. The **kill switch** blocks all new orders instantly.
5. **Orders & Positions** monitors open/filled orders (paper vs live clearly flagged)
   and lets an admin reconcile with the broker.

### Capital allocation & MTF

Three allocation methods are supported: **fixed**, **risk-based** (entry-to-stop
distance) and **hybrid** (the stricter of the two). Every portfolio limit — per-trade,
aggregate risk, sector exposure, gross exposure, cash reserve, max positions — is
enforced in `app/core/risk.py`. **MTF is OFF by default**; it is only usable when the
account/instrument eligibility and margin data are verified through authorized APIs.

### SELL signals (Indian market)

A multi-day cash short is not permitted on NSE. SELL setups are marked **analytical**
unless the configured product is **INTRADAY** or a verified **MTF** short; the
execution pipeline refuses to route an unsupported short.

---

## Testing

```bash
pytest -q
```

The suite (61 tests) covers the critical logic the system depends on:

- BUY/SELL price & direction correctness, tick rounding
- Stop/target placement and R:R rejection
- Position sizing and every capital/risk limit
- Invalidated-zone rejection, FVG detection/fill
- Market structure (swings, BOS/CHOCH, no-repaint-on-wick)
- Quality-score weighting and mandatory exclusions (missing data ⇒ zero points)
- Negative-news gating and fail-closed behaviour
- Scanner pipeline: offline publishes nothing; qualified candidate published with sizing
- Auto-trading OFF by default, kill switch, duplicate prevention, expiry, slippage,
  live-confirmation requirement
- API: auth gating, settings persistence, secrets never exposed

> Test output is real — run `pytest` to reproduce. No fabricated prices are ever used
> as live market data.

---

## Safety & disclaimer

This software assists analysis and optional authorized execution. It makes **no**
promise of profit, win rate or guaranteed returns, and the quality score is **not** a
calibrated probability. Trading involves risk of loss; leverage (MTF) amplifies it.
Review all configuration, verify broker API behaviour, and start with paper trading.
You are responsible for compliance with your broker's terms, exchange rules and
applicable regulations.
