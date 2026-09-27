<div align="center">

# 🧠 BTC Market Analysis Tool

### Your personal market intelligence desk — Bitcoin first, macro aware

**A data engineering + analytics pipeline that pulls live market data from the main public APIs and turns it into actionable market signals.**

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Pandas](https://img.shields.io/badge/Pandas-3.0-150458?logo=pandas&logoColor=white)](https://pandas.pydata.org/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#license)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

</div>

---

## 🚀 The Vision

> **Today:** an early-stage, modular pipeline that connects to the main public market APIs and stores real data — clean, swappable, and ready to grow.
>
> **Tomorrow:** your **fully personalized market dashboard** for:
>
> 📊 **Derivatives** — futures & options data · funding rates · open interest · basis
> ⛓️ **On-chain** — exchange flows · whale movements · realized cap · MVRV
> 🌍 **Macro** — CPI · GDP · non-farm payrolls · interest rates · money supply

One dashboard, built your way — Bitcoin-first, macro-aware, and under your full control.

---

## ⚡ Why It Exists

Public market dashboards are black boxes. This one is **yours**:

- 🧩 **Modular fetchers**: each data source is an isolated, swappable connector — add a new one in minutes.
- 🏗️ **Clean layering**: `fetchers → analytics → storage`, no spaghetti.
- 🎯 **Signal over noise**: a single composite market score out of 100 — boring tables, sharp decisions.
- 🗄️ **Local-first storage**: SQLite history you own, no cloud lock-in.
- 🧪 **Testable build**: run any fetcher solo from the CLI while you develop.

---

## 🧱 Current Stage

> ⚠️ **Early stage.** The project acquires and stores the core data from the **main market APIs**, scores it, and now serves it over a **REST API** — everything else is built on top of that foundation.

```
                    ┌──────────────────────────────┐
                    │       DATA SOURCES          │
                    │  Binance · Alternative.me   │
                    │  FRED · Yahoo Finance       │
                    └──────────────┬───────────────┘
                                   ▼
┌───────────────────────────────────────────────────┐
│              DATA LAYER (src/fetchers/)           │
│   BaseFetcher ──► BTCFetcher                      │
│                   FearGreedFetcher                │
│                   FREDFetcher                     │
│                   StockIndicesFetcher             │
└───────────────────────┬───────────────────────────┘
                        ▼
┌───────────────────────────────────────────────────┐
│          ANALYTICS LAYER (src/analytics/)         │
│   indicators.py ──► EMA-200 · RSI-14              │
│   scoring.py    ──► Composite market score        │
└───────────────────────┬───────────────────────────┘
                        ▼
┌───────────────────────────────────────────────────┐
│            STORAGE LAYER (src/storage/)           │
│   db_manager.py ──► SQLite daily metrics history  │
└───────────────────────┬───────────────────────────┘
                        ▼
┌───────────────────────────────────────────────────┐
│              API LAYER (src/api/)                 │
│   FastAPI ──► /api/dashboard  (one call, 9 blocks) │
│                /api/refresh    (live pipeline run) │
│                /api/{stocks,fear-greed,fred,…}    │
└───────────────────────────────────────────────────┘
```

---

## 🔌 Current Data Sources

| Source | Data | Fetcher | Auth |
|--------|------|---------|------|
| **Binance** | BTC/USDT daily OHLCV (klines) | `BTCFetcher` | none |
| **Alternative.me** | Fear & Greed Index | `FearGreedFetcher` | none |
| **FRED (St. Louis Fed)** | M2 money supply (YoY growth) | `FREDFetcher` | [free API key](https://fred.stlouisfed.org/docs/api/api_key.html) |
| **Yahoo Finance** | S&P 500, NASDAQ, DXY trend | `StockIndicesFetcher` | none |
| **Google Trends** | Search interest for "bitcoin" | `GoogleTrendsFetcher` | none |

---

## 🧮 The Market Score

A weighted composite of tradable signals, normalized to **0–100**, giving a read of how attractive the current market setup is:

> ⚙️ Weights were **calibrated empirically** against 8+ years of BTC forward returns (see [Backtesting & Calibration](#-backtesting--calibration)). The classic dip-buying signals (Fear & Greed, RSI oversold, below-EMA-200) proved *noise-to-negative* at a 90-day horizon, while retail disinterest (Google Trends) and momentum carry real signal.

| Signal | Weight | Logic |
|-------:|-------:|-------|
| Google Trends | 60% | Retail disinterest ⇒ accumulation (strongest signal) |
| MACD histogram | 16% | Momentum / trend reversal |
| DXY trend | 10% | Dollar strength vs. risk assets |
| M2 money supply | 5% | Liquidity conditions |
| EMA-200 | 4% | Price vs. long-term trend |
| Fear & Greed | 3% | Market sentiment |
| RSI-14 | 2% | Momentum / overbought–oversold |

### Zones

| Zone | Score | Mean 90d return (2017→2026) | Win rate | Mean 90d max drawdown |
|------|-------:|------------------------------:|---------:|----------------------:|
| **High accumulation** | ≥ 70 | +35.2% | 63.6% | −25.8% |
| **Moderate accumulation** | 50–69 | +15.0% | 56.0% | −24.4% |
| **Neutral** | 30–49 | +0.9% | 44.8% | −27.6% |
| **Selling zone** | < 30 | −11.5% | 31.2% | −35.4% |

---

## 🛠️ Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/<your-user>/btc-analysis-tool.git
cd btc-analysis-tool

# 2. Create & activate a virtual environment
python -m venv venv
# Windows (PowerShell)
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) Create a `.env` with your FRED API key (needed for M2 data)
```

---

## ▶️ Usage

### Run the full pipeline

```python
python main.py
```

> Fetches data → computes indicators → scores → saves to SQLite → prints the market summary and the **possible buys** (recommended share of your monthly investment for the current zone).
> All the pipeline logic lives in `src/fetchers/pipeline.py`.

### Test a single fetcher (dev mode)

```powershell
# All sources
python -m src.fetchers

# One source only
python -m src.fetchers btc
python -m src.fetchers fear_greed
python -m src.fetchers fred_m2
python -m src.fetchers stock_indices
```

> ⚙️ Edit `TARGET = "all"` in `src/fetchers/__init__.py` to choose the default fetcher tested.

### Historical data & backfill

```bash
# Full backfill: BTC, Fear & Greed, M2, Google Trends, stock indices (+ scores)
python -m src.storage.backfill all

# Or a single target: btc | fear_greed | fred_m2 | google_trends |
#                     stock_indices | indicators | scores
python -m src.storage.backfill stock_indices
python -m src.storage.backfill scores
```

### Sample output

```
[+] BTC: 250 candles
    Last=2026-09-22 close=$86,156.00
[+] Fear & Greed: 78
[+] M2 YoY: 2.4%
[+] Stocks: {'SP500': 7764.64, 'NASDAQ': 27244.28, 'DXY_trend': 'bullish'}
```

### 🌐 REST API

A read-only FastAPI service over the same SQLite database, built to feed a
dashboard without touching the CLI. Only `POST /api/refresh` goes out to the
network; everything else is served from disk.

```bash
python -m src.api          # http://127.0.0.1:8000  (docs at /docs)
```

| Env var | Default | Purpose |
|---------|---------|---------|
| `API_HOST` | `127.0.0.1` | Bind address |
| `API_PORT` | `8000` | Port |
| `API_RELOAD` | `0` | `1` enables uvicorn auto-reload |
| `API_CORS_ORIGINS` | `localhost:4200,127.0.0.1:4200,localhost:4300,127.0.0.1:4300` | Comma-separated allowed origins |

#### Endpoints

| Method | Route | Returns |
|--------|-------|---------|
| `GET` | `/api/dashboard?days=90` | The nine blocks described below, in one call |
| `POST` | `/api/refresh` | Runs the pipeline live, stores it, returns the report |
| `GET` | `/api/config` | Weights, zone thresholds, buy actions, component metadata |
| `GET` | `/api/score/history` | Stored daily scores (`metrics_history`) |
| `GET` | `/api/klines` | BTC/USDT daily candles (`btc_klines`) |
| `GET` | `/api/indicators` | Computed indicators (`btc_indicators`) |
| `GET` | `/api/fear-greed` | Fear & Greed index (`fear_greed_history`) |
| `GET` | `/api/fred` | M2 money supply (`fred_series`) |
| `GET` | `/api/stocks` | Equity and dollar data (`stock_history`) |
| `GET` | `/api/google-trends` | Search interest (`google_trends`) |
| `GET` | `/` | Route index, grouped by tag |

`GET /api/dashboard` bundles nine blocks: `report` (today's score), `zone` (streak,
thresholds, price context, distribution, transitions), `macro` (latest value of every
source), `config`, `backtest` (forward return per zone and horizon), `calibration`,
`health`, `history` (short score/price series) and `generated_at`.

```jsonc
// GET /api/dashboard  ->  report
{
  "date": "2026-09-27", "btc_price": 84498.88, "ema_200": 73369.2, "rsi_14": 65.21,
  "fear_greed": 70, "m2_yoy": 5.66, "sp500": 7743.41, "nasdaq": 27068.72,
  "dxy": "bullish", "macd_hist": 222.81, "google_trends": 29.0,
  "total_score": 63, "zone": "Moderate accumulation zone",
  "components": { "google_trends": 71, "macd": 100, "dxy": 0, "m2": 70.8,
                  "ema_200": 5, "fear_greed": 30, "rsi": 12 },
  "zone_history": { "n": 1667, "mean": 14.87, "win": 55.97 },
  "action": "COMPRA NORMAL (DCA)", "ratio": 0.5, "source": "stored"
}
```

The seven table endpoints share one contract and one set of query params:

| Param | Meaning |
|-------|---------|
| `?limit=` | Max rows, the most recent of the window (default **20**, max **365**) |
| `?date=` | One single day, `YYYY-MM-DD` |
| `?start=` `&end=` | Inclusive window, `YYYY-MM-DD` |

```jsonc
// GET /api/score/history?start=2026-09-01&end=2026-09-27
{
  "source": "scores", "table": "metrics_history",
  "date": null, "start": "2026-09-01", "end": "2026-09-27", "limit": 20,
  "count": 20,          // rows returned
  "total": 25,          // rows matching the window, before the limit
  "rows": [ { "date": "2026-09-01", "total_score": 47.0, "zone": "Neutral zone", /* … */ }, … ]
}
```

Rows always come oldest first, so a chart never has to reverse them. `total` tells
you whether more pages exist: walk backwards moving `end`. Bad input returns `422`
with a `detail` message, an unknown route `404`, and any unexpected error `500`
as JSON instead of a stack trace. The full contract lives in `/docs` and
`/openapi.json`.

---

## 📊 Backtesting & Calibration

The score is validated against history, not vibes. For every day with a stored score
it computes the BTC return **7 / 30 / 90 / 180 / 365 days later** and groups it by zone,
so the "buy cheap" hypothesis can be checked empirically. It also reports the **forward
max drawdown** per zone (worst peak-to-trough within 90/180d windows): the Selling zone
bottoms out ~10 points deeper than High accumulation, which is what that zone is really
for — protecting capital.

```bash
# Run the backtest (uses stored metrics_history + btc_klines)
python -m src.analytics.backtest

# Also run the --independent bootstrap + episode-level validation
python -m src.analytics.backtest --independent

# Save the per-day details to CSV
python -m src.analytics.backtest --csv backtest.csv
```

`src/analytics/calibrate.py` measures how much each component actually predicts
forward returns (per signal and per score bin) — the tool used to set the current weights:

```bash
python -m src.analytics.calibrate
```

### Historical depth

| Source | Goes back to |
|--------|--------------|
| BTC/USDT (Binance) | 2017-08-17 (pair listing) |
| Fear & Greed (Alternative.me) | 2018-02-01 (index launch) |
| S&P 500 · NASDAQ · DXY (Yahoo) | 2016-09 (10y range) |
| M2 (FRED) | 1959 |
| Google Trends | 2017-08 (monthly resolution beyond ~5y) |

Days before 2018-02-01 score with a neutral Fear & Greed value (50); the MA/RSI
indicators need ~200 trading days to warm up. Regenerate the whole history with
`python -m src.storage.backfill scores`.

---

## 🗺️ Roadmap

From data acquisition pipeline → **your personalized multi-layer market dashboard**.

### ✅ Done
- [x] Modular fetchers for BTC, Fear & Greed, M2, and stock indices
- [x] EMA-200, RSI-14 & MACD technical indicators
- [x] Composite market scoring engine
- [x] **Backtest validation of the score vs forward returns (8+ years)**
- [x] **Data-driven weight & zone calibration**
- [x] SQLite persistence with daily history
- [x] Standalone fetcher testing via CLI
- [x] **Read-only REST API over the stored data** (`GET /api/dashboard`, `POST /api/refresh`)
- [x] Public README & project scaffolding

### 🔜 Foundation (current focus)
- [ ] ==**Make every API respond reliably**== (retries, auto-fallback, health checks)
- [ ] M2 data without an API key (public FRED CSV drop-in)
- [ ] Fetcher unit tests + integration tests
- [ ] Expand FRED coverage → **CPI, GDP, non-farm payrolls, interest rates**

### 🧭 On the Horizon — Layered Data

- **📊 Derivatives**
  - [ ] Funding rates & perpetuals data
  - [ ] Open interest & liquidation maps
  - [ ] Futures basis & term structure
- **⛓️ On-chain**
  - [ ] Exchange inflows / outflows
  - [ ] Whale & miner movements
  - [ ] MVRV, realized cap & SOPR indicators
- **🌍 Macro**
  - [ ] CPI & PCE inflation trackers
  - [ ] GDP growth & PMIs
  - [ ] US non-farm payrolls & unemployment
  - [ ] Central bank interest rate decisions

### 🖥️ The Dashboard Era
- [ ] **Web dashboard** — the REST API is ready; the SPA on top of it is next
- [ ] Multi-asset watchlist: BTC + ETH + top alts + macro pairs
- [ ] Interactive candlestick charts with custom indicator overlay
- [ ] Cross-correlation explorer (BTC vs. macro vs. on-chain)
- [ ] Custom scoring models — assign your own weights
- [ ] Alerts (Telegram / email) on signals & macro releases
- [ ] Mobile-friendly responsive UI
- [ ] Export to CSV / Excel / JSON

---

## 🧰 Tech Stack

| Layer | Tech |
|-------|------|
| Language | Python 3.12+ |
| Data | pandas · numpy · requests |
| Storage | SQLite |
| API | FastAPI · Uvicorn · Pydantic |
| Config | python-dotenv |
| CLI | argparse |
| Vision | Charts (ECharts/Plotly) · Tailwind |

---

## 📁 Project Structure

```
btc-analysis-tool/
├── main.py                     # Pipeline entry point
├── requirements.txt
├── .env                        # Configuration (FRED_API_KEY, DB_PATH) — gitignored
├── data/                       # SQLite database (gitignored)
├── logs/                       # Application logs (gitignored)
└── src/
    ├── config.py               # Env-driven configuration
    ├── api/                    # Read-only REST API (FastAPI)
    │   ├── __main__.py         # `python -m src.api` entry point
    │   ├── app.py              # App factory, CORS, error handlers, route index
    │   ├── routers/            # dashboard · meta · history · report
    │   ├── queries.py          # Read models shared by every endpoint
    │   ├── schemas.py          # Pydantic response contracts
    │   ├── serializers.py      # pandas/numpy → JSON-safe values
    │   ├── params.py           # Query params and their validation
    │   └── cache.py            # TTL cache for the heavy frames
    ├── analytics/
    │   ├── indicators.py       # EMA-200, RSI-14, MACD
    │   ├── scoring.py          # Composite market scoring engine
    │   ├── backtest.py         # Forward-return validation by score zone
    │   └── calibrate.py        # Per-signal predictive-power diagnostics
    ├── diagnostics/
    │   └── data_coverage.py    # Per-table date range and row counts
    ├── fetchers/
    │   ├── base.py             # HTTP helper (headers, timeout, errors)
    │   ├── btc_binance.py      # Binance klines
    │   ├── fear_greed.py       # Fear & Greed Index
    │   ├── fred_m2.py          # FRED M2 money supply
    │   ├── google_trends.py    # Google Trends search interest
    │   ├── stock_indices.py    # S&P 500, NASDAQ, DXY
    │   └── pipeline.py         # fetch → score → buy actions (main flow)
    ├── storage/
    │   ├── backfill.py         # Historical data backfill CLI
    │   └── db_manager.py       # SQLite persistence
    └── utils/
        └── logger.py           # Shared logger setup
```

---

## 🤝 Contributing

Found a bug, want a new fetcher (derivatives, on-chain, macro), or have a killer indicator idea? Open an **issue** or a **PR** — contributions welcome!

---

## 📄 License

MIT

---

<div align="center">

**📡 Data first. Signals later. Dashboard soon.**

</div>