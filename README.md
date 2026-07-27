# Short Interest Tracker

A web app that ranks **US exchange-listed stocks by the percentage of their float that is sold short**,
using official **FINRA** short-interest data joined with market data (float, market cap, volume, price)
from Yahoo Finance. Includes a search bar and per-stock candlestick charts.

## What it shows

- **Ranking table** — every enriched stock ordered by *short % of float* (short interest ÷ float),
  with days-to-cover, float, market cap, $ daily volume, short interest and price. Columns are sortable.
- **Search bar** — look up any ticker or company name.
- **Stock detail** — float, market cap, $ daily volume, short interest, shares outstanding,
  short % of float / outstanding, plus an interactive **candlestick chart** (1M–5Y).

## Important caveat about the data

Short interest is **official FINRA data, published only twice a month** with a reporting lag of
roughly two weeks. The *short % of float* therefore updates only on each bi-monthly settlement date;
prices, volume and float update daily. This tool is informational only and **not investment advice**.

Rows where short % of float exceeds 100% (almost always a stale-float or post-split data artifact)
are flagged and excluded from the default ranking.

## Architecture

```
FINRA CSV ──┐
            ├─► pipeline (download → parse → enrich → compute) ─► SQLite ─► FastAPI ─► React UI
Yahoo JSON ─┘
```

- `backend/finra.py` — downloads the official FINRA bi-monthly file from
  `https://cdn.finra.org/equity/otcmarket/biweekly/shrt<YYYYMMDD>.csv` and loads exchange-listed
  rows (NYSE / Nasdaq / AMEX) into SQLite.
- `backend/market_data.py` — a small Yahoo Finance client (curl_cffi, browser-impersonating,
  single reused crumb) for fundamentals and OHLC candles. More reliable than yfinance's default
  session, which gets 429-throttled.
- `backend/enrich.py` — fetches float / market cap / volume per symbol and computes short % of float.
- `backend/main.py` — FastAPI endpoints consumed by the React frontend.
- `frontend/` — React + Vite + TypeScript, candlesticks via `lightweight-charts`.

## Prerequisites

- Python 3.12 and Node.js LTS (already installed on this machine).

## Setup & run

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Load data (downloads the latest FINRA file, then enriches the top 400 most-shorted names):

```bash
.venv\Scripts\python.exe pipeline.py --enrich 400
```

Start the API (http://127.0.0.1:8000):

```bash
.venv\Scripts\python.exe -m uvicorn main:app --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to the backend on port 8000.

## Expanding coverage

Enrichment is bounded and prioritized (largest short positions first) to respect Yahoo's rate limits.
Results persist in `backend/data.db`, so re-running enrichment fills in more of the ~8,600 exchange-listed
universe:

```bash
.venv\Scripts\python.exe pipeline.py --enrich-only 2000
```

Refresh the FINRA data only (e.g. after a new settlement date is published):

```bash
.venv\Scripts\python.exe pipeline.py --ingest-only
```

## API reference

| Endpoint | Purpose |
|---|---|
| `GET /api/meta` | Settlement date, counts, disclaimer |
| `GET /api/stocks?sort=short_pct_float&order=desc&page=1&page_size=50` | Ranked, paginated list |
| `GET /api/stocks/search?q=<term>` | Search by ticker or name |
| `GET /api/stocks/{ticker}` | Full detail for one stock |
| `GET /api/stocks/{ticker}/candles?range=1y&interval=1d` | OHLCV for the chart |

---

# Phase 2 — Research, alerts, and 24/7 monitoring

## Reason Short / Reason Short Squeeze

Two buttons on the stock detail page run one evidence pipeline and synthesize a
**verdict-first** explanation with citations:

| Source | What it contributes |
|---|---|
| **SEC EDGAR** | Shelf offerings & ATMs (`S-1/S-3/424B*`) = dilution, the classic short thesis; `8-K` material events; **`NT 10-K/Q` late filings = distress** |
| **FINRA history** | When short interest actually ramped — then pulls the filings from a ±5-day window around each inflection. This is what makes the answer *causal* |
| **SEC fails-to-deliver** | Settlement pressure |
| **News RSS** | Headlines + **short-seller report detection** (Hindenburg, Muddy Waters, Culper, …) |
| **StockTwits / Reddit** | Retail sentiment (bullish/bearish split, post volume) |
| **X / Twitter** | A compliant **deep-link button** — you read it yourself (see below) |

Set `ANTHROPIC_API_KEY` to enable the Claude synthesis layer. **Without a key
everything still works** — you get the raw evidence dashboard instead.

### Why X isn't automated

X removed its free API tier in Feb 2026 and its ToS prohibits *automated* access;
they litigate against scrapers. **No scraper exists in this codebase.** The
button opens X in your own browser — a human reading a page breaks no rules.
`sources/x_api.py` is an adapter stub if you ever add an official paid key.

## Multi-timeframe candles

1m / 5m / 15m / 1H / 1D. Illegal combinations are **clamped**, not errored —
Yahoo returns an *empty* chart for e.g. 1m over 1y, so `resolve_range()` silently
falls back to the largest legal range (1m → 7d).

## Alerts

Run the back-test before enabling anything:

```bash
cd backend && .venv\Scripts\python.exe scanner\backtest.py
```

It replays the rules over ~70,000 ticker-days and must reproduce the study:

| Metric | Study | Back-test |
|---|---|---|
| ≥2× squeeze events found | 205 | 203 |
| Recall at the +10% tier | 93.7% | **93.6%** |
| Precision | 10.4% | **10.4%** |
| Fires on SLS 2025-12-29 / HTZ 2025-11-04 | — | **both pass** |

### The rules, and why they look like this

A **structural gate** comes first — `short % of float ≥ 15` AND `days-to-cover ≥ 3`.
That, not volume, is the real noise filter.

| Tier | Trigger | Delivery |
|---|---|---|
| 🔵 Watch | ≥ +5% and RVOL ≥ 1.5× | in-app only |
| 🔔 Heads-up | ≥ **+10%** vs prev close | push, labelled `UNCONFIRMED — not an entry signal` |
| 🔴 Urgent | ≥ +20%, or ≥ +10% with RVOL ≥ 3× | high-priority push |
| ✅ Confirmed | **closed** ≥ +10% | push — the actual quality signal |
| 📈 Continuation | previously triggered, still making higher highs | daily digest |
| 🟡 Building | ≥2 up-days on 1.5–2.5× volume, cumulative ≥ +15% | daily digest |

Two counter-intuitive findings shaped this:

1. **Volume is never required.** 19% of real ≥2× squeezes ignited on *below-average*
   volume (GME 2021-02-22 fired at 0.3× and still ran 8.6×). Requiring volume ≥3×
   alongside +10% drops recall from 93.7% to **30.7%**.
2. **Never trigger on a single bar.** On days that reached +10%, the average largest
   single 5-minute bar was only **2.82%** — a "≥5% in one 5-min bar" rule misses 93%
   of them while still firing ~30×/day on a 50-stock list.

Catalyst detection is a **label, never a filter** — an alert with no findable news
still fires, it just says so.

```bash
python -m scanner.run_scan --dry-run   # evaluate, never push
python -m scanner.run_scan             # live
python -m scanner.run_scan --close     # post-close confirmation pass
```

Set `NTFY_TOPIC` to a private topic name and subscribe to it in the
[ntfy](https://ntfy.sh) app to receive pushes on your phone.

## 24/7 without your PC

`.github/workflows/scan.yml` runs every 5 minutes on GitHub's runners.

| Constraint | How it's handled |
|---|---|
| Private repos get only 2,000 free min/month | **Repo must be public** (public = unlimited) |
| Runners are ephemeral | Watchlist + cooldown persist as JSON on a `state` branch |
| Schedules auto-disable after 60 days idle | The daily watchlist refresh doubles as a heartbeat |
| Delays of 10–30 min at peak | Runs are stateless; a late run still catches the move |
| Secrets | `NTFY_TOPIC`, `ANTHROPIC_API_KEY` in **GitHub Secrets**, never committed |

The job exits in seconds when the market is closed, keeping 288 runs/day cheap.

## ⚠️ Honest limitations

- **Precision is ~10%.** About 9 of 10 alerts will *not* become a 2× squeeze. That's
  inherent — pushing recall to 94% necessarily admits false positives.
- **These signals are descriptive, not predictive.** HTZ on 2025-11-04 gave *zero*
  technical warning: flat at 1.0× volume, then +36% on 13× volume.
- **~73% of squeezed stocks retraced** to within 30% of pre-squeeze levels within 90 days.
- **An intraday heads-up is not an entry signal** — 16.1% of even the *successful*
  events closed day 0 below the +10% crossing price. That's why the push says so.
- **Alert latency is ~5–20 min** (cron granularity + GitHub delays). Not for fast
  intraday trading.
- **Daily short volume ≠ short interest.** Short volume is *flow* and includes
  market-maker hedging; a stock can print 50% short volume daily with zero change in
  short interest. Only the bi-monthly figure gives "% of float shorted".
- **Not investment advice.**

## Data sources

- **FINRA** — official consolidated equity short interest (bi-monthly) + daily short volume.
- **Yahoo Finance** — float, shares outstanding, market cap, price, volume, candles.
- **SEC EDGAR / fails-to-deliver** — filings and settlement data (free, no key).
- **StockTwits / Reddit / news RSS** — sentiment and headlines.
