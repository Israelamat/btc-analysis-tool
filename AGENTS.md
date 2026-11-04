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
& .\venv\Scripts\python.exe -m pytest -q                         # unit tests
& .\venv\Scripts\python.exe -m src.analytics.backtest [--long-term] [--independent] [--csv path]
& .\venv\Scripts\python.exe -m src.analytics.calibrate         # component diagnostics
& .\venv\Scripts\python.exe -m src.analytics.chart --open      # interactive buy-point HTML
& .\venv\Scripts\python.exe -m src.analytics.tactical_calibration  # 90d feature audit
& .\venv\Scripts\python.exe -m src.analytics.tactical_backtest     # 90d DCA evaluation
& .\venv\Scripts\python.exe -m src.fetchers [target]           # dev fetcher smoke test
```

Backfill targets: `all | btc | fear_greed | fred_m2 | google_trends | stock_indices | derivatives | indicators | scores`

Note: `python -m main.py` does **not** work (`-m` needs a module name, not a file).
Use `python main.py` (or `python -m main`).

## Architecture

```
main.py                       thin entry -> calls src.fetchers.pipeline.run_pipeline()
src/fetchers/
  base.py                     HTTP helper (headers, timeouts, retries)
  btc_binance.py              Binance BTC/USDT daily klines (full history pagination)
  binance_futures.py          USD-M futures daily klines (taker flow) + funding history
  fear_greed.py               Alternative.me Fear & Greed (limit=0 => whole history)
  fred_m2.py                  FRED M2 money supply (requires FRED_API_KEY, None on fail)
  google_trends.py            "bitcoin" search interest (pytrends)
  stock_indices.py            S&P 500, NASDAQ closes + DXY trend (Yahoo Finance)
  pipeline.py                 THE main flow (fetch -> indicators -> score -> buy report)
src/analytics/
  indicators.py               EMA-200, RSI-14, MACD (single-day + full series)
  scoring.py                  BTCAcumulationScorer: available signals -> renormalized score
  backtest.py                 7/30/90/180/365/730d returns by zone + cycle/DCA checks
  calibrate.py                per-component correlation vs 90d forward return
  tactical_features.py        90d no-lookahead panel (funding/basis/CVD/sentiment)
  tactical_calibration.py     per-feature IC, deciles and subperiod stability
  tactical_backtest.py        90d score candidates + modulated DCA evaluation
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

| Zone | Score | Mean 90d return | Win 90d |
|------|------:|------:|------:|
| High accumulation | ≥ 70 | +11.0% | 48.9% |
| Moderate | 50–69 | +21.2% | 50.1% |
| Neutral | 30–49 | +22.5% | 63.1% |
| Selling zone | < 30 | +10.2% | 51.5% |

**Cycle-level validation (Oct 2026)**: the score is a 730d cycle anchor, not a
30/90d timer. Correlation rises with horizon: 30d −0.033, 90d 0.005, 180d 0.047,
365d 0.178, **730d 0.392**. Temporal stability split at 2022-01-01: 730d Spearman
+0.498 before / +0.331 after (stable); 365d +0.346 / −0.059 (not stable). Cycle
returns by zone (365d / 730d mean, win): High +124.8%/87.5% and +378.4%/97.1%;
Moderate +60.4%/55.8% and +187.1%/80.0%; Neutral +81.6%/59.6% and +157.6%/72.2%;
Selling +36.4%/57.7% and +75.5%/57.6%. Monthly DCA scaled 0.5x–1.5x bought at a
**9.0% lower average cost** than flat DCA (111 months, in-sample, overlapping).

Correlation score vs 90d forward return: **≈ 0 (was ~+0.23 before re-weighting)**.
The zones no longer separate 90d forward returns on the sample; historical decisions
that produced the +0.23 calibration:

- fear_greed/rsi/ema-contarian signals proved *negative/noise* predictors at 90d → previously down-weighted (they are up again since Oct 2026 by design).
- m2 flipped negative after 2022 → weight kept low (0.05).
- Zone thresholds were moved from 80/60/40 to **70/50/30**.
- Oct 2026: the owner re-weighted the model toward on-chain (proxy_mvrv 0.25,
  proxy_nupl 0.15) at the expense of Google Trends (0.60 → 0.12). Calibration
  showed the cost (correalation +0.23 → 0.008) and the change was kept anyway.

## 90-day tactical experiment (Oct 2026) — evaluated, NOT integrated

A parallel research track asked whether free derivatives data could build a
90-day `tactical_score` that modulates the monthly DCA (0.5x–1.5x) without
touching the 12-month cycle score. The fetchers/storage/audit are implemented;
the allocation overlay is **deliberately not wired into `pipeline.py`** because
the evidence did not support it.

- `src/fetchers/binance_futures.py` pulls USD-M daily klines (incl. taker buy
  volume → CVD proxy) and 8h funding rates (aggregated daily), from 2019-09.
- `backfill derivatives` stores `futures_klines` and `funding_history`.
- `src/analytics/tactical_features.py` builds a no-lookahead panel: funding,
  basis, taker delta/CVD, past returns, RSI, Fear & Greed, Google Trends,
  MVRV/NUPL percentiles, plus forward 90d returns/drawdowns.
- `tactical_calibration` reports monthly Spearman IC and subperiod stability;
  `tactical_backtest` compares candidate scores and a 0.5x–1.5x modulated DCA
  against flat DCA.

Findings (2019-09 → 2026-10, 84 monthly samples, in-sample):

| Candidate | IC 90d | IC 2019-21 | IC 2022-24 | IC 2024+ | DCA cost vs flat |
|-----------|------:|------:|------:|------:|------:|
| derivatives contrarian (funding/basis/CVD) | -0.004 | 0.324 | -0.418 | 0.100 | -9.3% (worse) |
| sentiment momentum (FG/RSI/Trends pct) | 0.260 | 0.489 | 0.301 | -0.075 | -1.7% (worse) |
| combined | 0.195 | 0.597 | -0.223 | 0.065 | -5.8% (worse) |
| Google Trends contrarian (100 − value) | 0.234 | 0.021 | 0.421 | 0.368 | +4.5% (better) |
| existing cycle score | -0.065 | 0.161 | -0.351 | -0.036 | +5.3% (better) |

- **Derivatives do not separate 90d returns**: funding/basis sign flips across
  subperiods and the CVD signal is unstable. Do not add them as an allocation
  modifier on this sample.
- The only stable 90d signal is Google Trends contrarian, which is already in
  the cycle score (weight 0.12) and has monthly resolution beyond ~5y.
- The cycle score has near-zero 90d IC but still lowers DCA average cost
  (+5.3%) and slightly improves max drawdown, i.e. it works as a cycle/anchor
  filter rather than a 90d timer.
- Caveat: these DCA comparisons are in-sample and monthly observations overlap
  by horizon; treat them as a screen, not a validated edge. No walk-forward
  allocation was promoted.

## Data sources & historical depth

| Source | Goes back to |
|--------|--------------|
| BTC/USDT (Binance) | 2017-08-17 (pair listing, full pagination) |
| BTCUSDT USD-M futures + funding (Binance) | 2019-09-08 (perpetual listing) |
| Fear & Greed (Alternative.me) | 2018-02-01 (limit=0 gives everything) |
| S&P 500 / NASDAQ / DXY (Yahoo) | 2016-09 (range "10y") |
| M2 (FRED) | 1959 (limit raised to 20000) |
| Google Trends | 2017-08 (pytrends; monthly resolution beyond ~5y) |

Storage: SQLite at `data/macro_crypto.db` (gitignored). Tables: `btc_klines`,
`btc_indicators`, `metrics_history` (daily score + zone + components JSON +
`coverage`), `fear_greed_history`, `fred_series`, `stock_history`, `google_trends`,
`futures_klines` (taker flow / CVD inputs), `funding_history` (daily aggregate).

Backfill scores: missing sources (Fear & Greed before 2018-02, Google Trends
before 2017-08, DXY before 2016-09) are passed as `None` and renormalized, not
filled with a neutral; EMA-200/RSI still need ~200 candles to warm up.

## Known gotchas / rules of thumb

- **Google Trends `"today 1-y"` timeframe returns HTTP 400** from Google. Always use
  explicit date ranges (`"{start} {end}"`) — that is the current implementation.
- **Binance funding `startTime=0` returns the latest page**, not history. Pagination
  starts at `FUNDING_START_MS` (2019-09-01) in `binance_futures.py`; without it the
  backfill silently stores only ~5 months of funding.
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
- `tests/` holds the pytest suite (scoring, indicators, backtest, DB upserts,
  futures parsing, trailing percentile, DCA math); run `python -m pytest -q`.
  No lint/typecheck script is configured — run edits with a real command
  (e.g. `python main.py` or a backfill) to verify.
- Fetchers log via `setup_logger()`; fetching errors are WARNINGs when the signal
  can be treated as missing, ERRORs when the pipeline must abort (e.g. no BTC).

## Conventions

- Do **not** add code comments unless asked.
- Commit style follows conventional commits: `feat:`, `fix:`, `refactor:`, etc.
- Only commit when the user explicitly asks. Inspect `git status`/`git diff` first.
- Match existing style: type hints, `setup_logger()`, `Config` from `src/config.py`,
  pandas DataFrames for series/history.
- The user communicates in Spanish; code/docs/commits stay in English as today.

## Current state (Oct 2026)

Fetchers, backfill, scoring, backtest and calibration are done and validated over
8.5 years. Derivatives data (funding/basis/taker flow) is fetched, stored and
audited, but the 90d tactical overlay is not integrated (see the experiment
section). The roadmap (in README) points to reliability hardening, a web dashboard
(FastAPI + SPA), multi-asset watchlist, on-chain/macro layers, alerts,
and CSV/Excel export.

`backtest.py` runs overlapping horizons (7/30/90/180/365/730d) plus, with
`--independent`, a non-overlapping bootstrap section and an episode-level validation
(one return per consecutive-day run) with exact binomial p-values and a Bayesian
posterior P(win < 50%). It also reports forward **max drawdowns**
(90/180/365/730d, daily and per episode), the score correlation by horizon, temporal
stability split at 2022 (`--split`), and a monthly flat-vs-scaled DCA comparison.
Use `--long-term` to skip the 30/90d tables and print only the 365/730d cycle view;
`--long-term --independent` also restricts bootstrap/episodes to 365/730d. Every run
ends with a **cycle playbook**: one buy per High episode, sold at the first later
Selling episode; open buys are marked to the latest close. It shows realized and
unrealized trades, win rate and mean/median returns.

Key results: correlation grows with horizon (730d +0.39, stable; 365d +0.18,
unstable after 2022). At 730d, High accumulation has a +378% mean and 97% win rate
vs Selling +76% and 58%. Drawdowns are **not** the differentiator: 90d High ≈ −24.9%
vs Selling ≈ −25.2%; 730d High ≈ −50.8% vs Selling ≈ −56.0%. Scaled DCA lowered
average cost ~9% over 111 months, but the sample is in-sample, overlapping and only
~2–4 independent cycles. Older claim that Selling bottoms ~10 points deeper was
wrong and has been removed.