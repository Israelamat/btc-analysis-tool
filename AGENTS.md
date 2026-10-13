# AGENTS.md — BTC Market Analysis Tool

Project context for AI assistants (opencode, Claude, Cursor, etc.). Read this first.

## What this project is

A **Bitcoin accumulation analysis tool**. It fetches market data from public APIs
(Binance, Alternative.me, FRED, Yahoo Finance, Google Trends), runs light analytics,
computes a **BTC accumulation score (0–100)** and prints a **"possible buys"** report:
how much of the monthly investment to deploy based on the current score zone.

Designed to be run from `python main.py` (thin entry). All pipeline logic lives in
`src/fetchers/pipeline.py`, inside the fetchers layer.

Language of the project owner: **Spanish** — answer the user in Spanish.

## Quick start / key commands

```bash
python -m venv venv                      # Windows PowerShell: venv\Scripts\Activate.ps1
& .\venv\Scripts\python.exe -m pip install -r requirements.txt

& .\venv\Scripts\python.exe main.py      # live pipeline: fetch -> score -> buy actions
& .\venv\Scripts\python.exe -m src.storage.backfill <target>   # see targets below
& .\venv\Scripts\python.exe -m src.analytics.backtest [--csv path]  # validation
& .\venv\Scripts\python.exe -m src.analytics.calibrate         # component diagnostics
& .\venv\Scripts\python.exe -m src.analytics.chart --open      # interactive buy-point HTML
& .\venv\Scripts\python.exe -m src.fetchers [target]           # dev fetcher smoke test
```

Backfill targets: `all | btc | fear_greed | fred_m2 | google_trends | stock_indices | indicators | scores`

Note: `python -m main.py` does **not** work (`-m` needs a module name, not a file).
Use `python main.py` (or `python -m main`).

## Architecture

```
main.py                       thin entry -> calls src.fetchers.pipeline.run_pipeline()
src/fetchers/
  base.py                     HTTP helper (headers, timeouts, retries)
  btc_binance.py              Binance BTC/USDT daily klines (full history pagination)
  fear_greed.py               Alternative.me Fear & Greed (limit=0 => whole history)
  fred_m2.py                  FRED M2 money supply (requires FRED_API_KEY, None on fail)
  google_trends.py            "bitcoin" search interest (pytrends)
  stock_indices.py            S&P 500, NASDAQ closes + DXY trend (Yahoo Finance)
  pipeline.py                 THE main flow (fetch -> indicators -> score -> buy report)
src/analytics/
  indicators.py               EMA-200, RSI-14, MACD (single-day + full series)
  scoring.py                  BTCAcumulationScorer: available signals -> renormalized score
  backtest.py                 forward 7/30/90d returns grouped by zone
  calibrate.py                per-component correlation vs 90d forward return
  chart.py                    interactive buy-point HTML (Chart.js, no new deps)
src/storage/
  backfill.py                 historical backfill CLI (scores regenerated here)
  db_manager.py               SQLite persistence (upserts, loaders, table_counts)
src/config.py                 Config: FRED_API_KEY, DB_PATH, START_DATE, SCORE_WEIGHTS
src/utils/logger.py           setup_logger()
```

## The scoring model (on-chain-anchored weights — calibrated, then redesigned)

Weights live in `src/config.py` `SCORE_WEIGHTS`; transform functions in
`scoring.py`: each component maps a raw signal to 0–100 (higher = "more
attractive to accumulate"), then the weighted average is clipped to 0–100 and
classified into zones.

The current weights (Oct 2026) are an **on-chain-anchored design**: 40% on the
Price/SMA-365 valuation proxies (`proxy_mvrv` + `proxy_nupl`), 28% technical,
15% macro/liquidity, 17% retail sentiment. This replaced the empirically
calibrated mix (Google Trends 60%) because the owner wanted the cycle's cost
basis to lead. Calibration after the change: **total score correlation ≈ 0**
with the 90d forward return (was +0.23) — proxy_mvrv/nupl themselves are
*mildly negative* predictors on the sample, and Google Trends remains the
strongest predictor (+0.27) but is capped at 0.12. The model is kept as a
design choice; `calibrate` documents the trade-off.

**Missing signals are never fabricated.** A source that fails returns `None`
(fetchers), so `BTCAcumulationScorer.calculate` scores only the available
components and renormalizes over their weights: `score = Σ(comp·w) / Σw`.
It also returns `coverage` (= Σw of the available signals, 1.0 = all present),
`missing`, `raw_zone` (before the cap) and `low_confidence`. When
`coverage < Config.COVERAGE_MIN` (default 0.5, env `COVERAGE_MIN`) the zone is
capped — High → Moderate, Selling → Neutral — so a couple of weak signals
cannot trigger a strong buy/sell. `metrics_history` stores the daily `coverage`.

| Component | Weight | Meaning of high value |
|-----------|-------:|------------------------|
| proxy_mvrv | 0.25 | price far below its 365-session average (MVRV = Price/SMA-365) — core anchor |
| proxy_nupl | 0.15 | deep unrealized losses (NUPL = 1 − 1/MVRV, contrarian) — core anchor |
| macd | 0.13 | bullish MACD histogram momentum |
| google_trends | 0.12 | LOW search interest (contrarian: 100 − value) — **best predictor** |
| ema_200 | 0.10 | price far below EMA-200 (dip) |
| dxy | 0.10 | weak dollar (bearish trend) |
| rsi | 0.05 | oversold (below 70) |
| fear_greed | 0.05 | extreme fear (100 − value) |
| m2 | 0.05 | high M2 YoY growth (amplia liquidez) |

Both valuation proxies share the same symmetric 0–100 transform (`valuation_score`
in `scoring.py`, also reused by `/api/valuation`): neutral center → 50,
center − span → 100, center + span → 0. `proxy_mvrv` uses
`VALUATION_RATIO_CENTER` (1.0) / `VALUATION_RATIO_SPAN` (0.3); `proxy_nupl` uses
`NUPL_CENTER` (0.0) / `NUPL_SPAN` (0.4). Before 2018-08-16 the SMA-365 is not
defined, so both components are missing and the score renormalizes.

Zones (`_classify` in `scoring.py`, mirrored in `backtest.ZONE_BUCKETS`):

| Zone | Score | Historical mean 90d return | Win rate |
|------|------:|------:|------:|
| High accumulation | ≥ 70 | +11.4% | 49.9% |
| Moderate | 50–69 | +21.0% | 51.4% |
| Neutral | 30–49 | +21.8% | 63.1% |
| Selling zone | < 30 | +10.2% | 51.5% |

Correlation score vs 90d forward return: **≈ 0 (was ~+0.23 before re-weighting)**.
The zones no longer separate forward returns on the sample; historical decisions
that produced the +0.23 calibration:

- fear_greed/rsi/ema-contarian signals proved *negative/noise* predictors at 90d → previously down-weighted (they are up again since Oct 2026 by design).
- m2 flipped negative after 2022 → weight kept low (0.05).
- Zone thresholds were moved from 80/60/40 to **70/50/30**.
- Oct 2026: the owner re-weighted the model toward on-chain (proxy_mvrv 0.25,
  proxy_nupl 0.15) at the expense of Google Trends (0.60 → 0.12). Calibration
  showed the cost (correalation +0.23 → 0.008) and the change was kept anyway.

## Data sources & historical depth

| Source | Goes back to |
|--------|--------------|
| BTC/USDT (Binance) | 2017-08-17 (pair listing, full pagination) |
| Fear & Greed (Alternative.me) | 2018-02-01 (limit=0 gives everything) |
| S&P 500 / NASDAQ / DXY (Yahoo) | 2016-09 (range "10y") |
| M2 (FRED) | 1959 (limit raised to 20000) |
| Google Trends | 2017-08 (pytrends; monthly resolution beyond ~5y) |

Storage: SQLite at `data/macro_crypto.db` (gitignored). Tables: `btc_klines`,
`btc_indicators`, `metrics_history` (daily score + zone + components JSON +
`coverage`), `fear_greed_history`, `fred_series`, `stock_history`, `google_trends`.

Backfill scores: missing sources (Fear & Greed before 2018-02, Google Trends
before 2017-08, DXY before 2016-09) are passed as `None` and renormalized, not
filled with a neutral; EMA-200/RSI still need ~200 candles to warm up.

## Known gotchas / rules of thumb

- **Google Trends `"today 1-y"` timeframe returns HTTP 400** from Google. Always use
  explicit date ranges (`"{start} {end}"`) — that is the current implementation.
- If the fresh Google Trends fetch fails it returns **None**, and the pipeline
  falls back to a recently stored DB value (< 30 days old) if available;
  otherwise the signal is treated as missing (score renormalizes, coverage drops).
- Sub-scores **saturate to their clamp bounds** (e.g. ema_200 floor 5, rsi floor 0
  when RSI > 70, dxy 0 when dollar bullish). This is by design and those components
  carry low weight, but a very high/very low total may look "flat" on extreme days.
- `FREDFetcher` requires `FRED_API_KEY` in `.env` (or env); without it M2 is
  missing (`None`, renormalized) instead of a fabricated 0%. `.env.example` was
  deleted; docs just mention creating `.env`.
- The DB is populated via backfill; `main.py` works without it (fresh fetch) but
  prefers stored full-history indicator values for consistency.
- **No tests yet** and no lint/typecheck script configured — run edits with a real
  command (e.g. `python main.py` or a backfill) to verify.
- Fetchers log via `setup_logger()`; fetching errors are WARNINGs when the signal
  can be treated as missing, ERRORs when the pipeline must abort (e.g. no BTC).

## Conventions

- Do **not** add code comments unless asked.
- Commit style follows conventional commits: `feat:`, `fix:`, `refactor:`, etc.
- Only commit when the user explicitly asks. Inspect `git status`/`git diff` first.
- Match existing style: type hints, `setup_logger()`, `Config` from `src/config.py`,
  pandas DataFrames for series/history.
- The user communicates in Spanish; code/docs/commits stay in English as today.

## Current state (Sep 2026)

Fetchers, backfill, scoring, backtest and calibration are done and validated over
8.5 years. The roadmap (in README) points to reliability hardening, a web dashboard
(FastAPI + SPA), multi-asset watchlist, derivatives/on-chain/macro layers, alerts,
and CSV/Excel export.

`backtest.py` runs overlapping horizons (7/30/90/180/365d) plus, with `--independent`,
a non-overlapping bootstrap section and an episode-level validation (one return per
consecutive-day run) with exact binomial p-values and a Bayesian posterior
P(win < 50%). Newer: a forward **max drawdown** report (90/180d, daily and per
episode) that shows the Selling zone bottoms out ~10 points deeper than High
accumulation, which is the zone's real purpose (protecting capital). Note: 109
"Selling zone" days are only ~23 episodes and ~5-7 market cycles, so its negative
edge is best supported by the mean at 180d
(P(mean<0) ≈ 82%), not by its win rate.