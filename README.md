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

> ⚠️ **Early stage.** Right now the project connects to the **main market APIs** to acquire and store the core data — everything else is built on top of that foundation.

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

| Zone | Score | Mean 90d return (2017→2026) | Win rate |
|------|-------:|------------------------------:|---------:|
| **High accumulation** | ≥ 70 | +35.2% | 63.6% |
| **Moderate accumulation** | 50–69 | +15.0% | 56.0% |
| **Neutral** | 30–49 | +0.9% | 44.8% |
| **Not a good zone** | < 30 | −11.5% | 31.2% |

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

---

## 📊 Backtesting & Calibration

The score is validated against history, not vibes. For every day with a stored score
it computes the BTC return **7 / 30 / 90 days later** and groups it by zone, so the
"buy cheap" hypothesis can be checked empirically.

```bash
# Run the backtest (uses stored metrics_history + btc_klines)
python -m src.analytics.backtest

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
- [ ] **Web dashboard** (FastAPI + lightweight SPA) — your own private trading desk
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
| Config | python-dotenv |
| CLI | argparse |
| Vision | FastAPI · Charts (ECharts/Plotly) · Tailwind |

---

## 📁 Project Structure

```
btc-analysis-tool/
├── main.py                     # Pipeline entry point
├── requirements.txt
├── .env.example                # Configuration template
├── data/                       # SQLite databases (gitignored)
├── logs/                       # Application logs (gitignored)
└── src/
    ├── config.py               # Env-driven configuration
    ├── analytics/
    │   ├── indicators.py       # EMA-200, RSI-14, MACD
    │   ├── scoring.py          # Composite market scoring engine
    │   ├── backtest.py         # Forward-return validation by score zone
    │   └── calibrate.py        # Per-signal predictive-power diagnostics
    ├── fetchers/
    │   ├── base.py             # HTTP helper (headers, timeout, errors)
    │   ├── btc_binance.py      # Binance klines
    │   ├── fear_greed.py       # Fear & Greed Index
    │   ├── fred_m2.py          # FRED M2 money supply
    │   ├── google_trends.py    # Google Trends search interest
    │   ├── stock_indices.py    # S&P 500, NASDAQ, DXY
    │   └── pipeline.py         # fetch → score → buy actions (main flow)
    └── storage/
        ├── backfill.py         # Historical data backfill CLI
        └── db_manager.py       # SQLite persistence
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