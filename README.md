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

| Signal | Weight | Logic |
|-------:|-------:|-------|
| EMA-200 | 25% | Price vs. long-term trend |
| M2 money supply | 20% | Liquidity conditions |
| Fear & Greed | 20% | Market sentiment extremes |
| RSI-14 | 15% | Momentum / overbought–oversold |
| DXY trend | 10% | Dollar strength vs. risk assets |
| MACD histogram | 5% | Momentum / trend reversal |
| Google Trends | 5% | Retail interest (contrarian) |

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

# 4. Configure environment (FRED key optional)
cp .env.example .env
```

---

## ▶️ Usage

### Run the full pipeline

```python
python main.py --run
```

> Fetches data → computes indicators → scores → saves to SQLite → prints the summary.

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

### Sample output

```
[+] BTC: 250 candles
    Last=2026-09-22 close=$86,156.00
[+] Fear & Greed: 78
[+] M2 YoY: 2.4%
[+] Stocks: {'SP500': 7764.64, 'NASDAQ': 27244.28, 'DXY_trend': 'bullish'}
```

---

## 🗺️ Roadmap

From data acquisition pipeline → **your personalized multi-layer market dashboard**.

### ✅ Done
- [x] Modular fetchers for BTC, Fear & Greed, M2, and stock indices
- [x] EMA-200 & RSI technical indicators
- [x] Composite market scoring engine
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
    │   ├── indicators.py       # EMA-200, RSI-14
    │   └── scoring.py          # Composite market scoring engine
    ├── fetchers/
    │   ├── base.py             # HTTP helper (headers, timeout, errors)
    │   ├── btc_binance.py      # Binance klines
    │   ├── fear_greed.py       # Fear & Greed Index
    │   ├── fred_m2.py          # FRED M2 money supply
    │   ├── google_trends.py    # Google Trends search interest
    │   └── stock_indices.py    # S&P 500, NASDAQ, DXY
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