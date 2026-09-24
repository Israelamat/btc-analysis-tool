"""Validate the accumulation score against forward BTC returns.

For every day with a recorded score, computes the BTC return over the
following 7/30/90/180/365 calendar days and groups it by score zone, so
the contrarian "buy when cheap" hypothesis can be checked empirically. An
optional non-overlapping bootstrap section validates how much of the edge
survives on statistically independent samples.
"""

import argparse
import math

import numpy as np
import pandas as pd

from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

HORIZONS = (7, 30, 90, 180, 365)
INDEPENDENT_HORIZONS = (30, 90, 180, 365)
DRAWDOWN_HORIZONS = (90, 180)
ZONE_BUCKETS = (
    (70.0, "High accumulation zone"),
    (50.0, "Moderate accumulation zone"),
    (30.0, "Neutral zone"),
    (float("-inf"), "Selling zone"),
)


def _bucket(score: pd.Series) -> pd.Series:
    """Map scores to the same zones used by the scorer."""
    out = pd.Series("Selling zone", index=score.index, dtype="object")
    for threshold, label in ZONE_BUCKETS:
        out[score >= threshold] = label
    return out


def _load_klines(db: DatabaseManager) -> pd.DataFrame:
    klines = db.load_btc_klines()
    if klines.empty:
        return pd.DataFrame(columns=["close", "date"])
    klines["date"] = pd.to_datetime(klines["date"])
    return klines.sort_values("date").set_index("date")


def forward_return(
    klines: pd.DataFrame, scored_dates: pd.DatetimeIndex, horizon: int
) -> pd.Series:
    """Return in % for each scored date, `horizon` calendar days later."""
    future_close = klines["close"].reindex(
        scored_dates + pd.Timedelta(days=horizon), method="ffill"
    )
    base_close = klines["close"].reindex(scored_dates, method="ffill")
    returns = (future_close.to_numpy() / base_close.to_numpy() - 1) * 100
    return pd.Series(returns, index=scored_dates)


def forward_max_drawdown(
    klines: pd.DataFrame, scored_dates: pd.DatetimeIndex, horizon: int
) -> pd.Series:
    """Worst peak-to-trough decline (%) inside each forward `horizon`-day window.

    Unlike returns this captures the journey: a zone that ends green at 365d
    can still lose -40% before recovering. Negative values, lower is worse.
    """
    close = klines["close"].to_numpy(dtype=float)
    close_dates = klines.index
    out = np.full(len(scored_dates), np.nan)
    for i, date in enumerate(scored_dates):
        start = close_dates.searchsorted(date, side="left")
        end = close_dates.searchsorted(
            date + pd.Timedelta(days=horizon), side="right"
        )
        window = close[start:end]
        if len(window) == 0:
            continue
        peak = np.maximum.accumulate(window)
        out[i] = float((window / peak - 1).min() * 100)
    return pd.Series(out, index=scored_dates)


def sample_independent(dates: pd.DatetimeIndex, horizon: int) -> pd.DatetimeIndex:
    """Keep dates spaced at least `horizon` days apart (non-overlapping picks)."""
    picks = []
    last = None
    for date in dates:
        if last is None or (date - last).days >= horizon:
            picks.append(date)
            last = date
    return pd.DatetimeIndex(picks)


def _bootstrap_replicates(
    values: pd.Series, stat, n_resamples: int, seed: int
) -> np.ndarray:
    """Bootstrap samples of `stat` over `values` (fixed seed for determinism)."""
    arr = values.to_numpy(dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return np.empty(0)
    rng = np.random.default_rng(seed)
    boot = np.empty(n_resamples)
    for i in range(n_resamples):
        boot[i] = stat(rng.choice(arr, size=arr.size, replace=True))
    return boot


def bootstrap_ci(
    values: pd.Series,
    stat=np.mean,
    n_resamples: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for `stat` over `values`."""
    boot = _bootstrap_replicates(values, stat, n_resamples, seed)
    if boot.size == 0:
        return np.nan, np.nan
    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def _probability_mean_negative(
    values: pd.Series, n_resamples: int = 2000, seed: int = 42
) -> float:
    """Fraction of bootstrapped means below zero (probability mean < 0)."""
    boot = _bootstrap_replicates(values, np.mean, n_resamples, seed)
    if boot.size == 0:
        return np.nan
    return float((boot < 0).mean())


def _episode_first_dates(frame: pd.DataFrame) -> pd.DatetimeIndex:
    """First date of every consecutive-day run for a single zone."""
    dates = pd.DatetimeIndex(frame["date"])
    picks = []
    last = None
    for date in dates:
        if last is None or (date - last).days > 1:
            picks.append(date)
        last = date
    return pd.DatetimeIndex(picks)


def _binomial_cdf(k: int, n: int) -> float:
    """P(X <= k) for X ~ Binomial(n, 0.5)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    total = sum(math.comb(n, j) * 0.5**n for j in range(k + 1))
    return min(total, 1.0)


def summarize(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for zone, group in metrics.groupby("zone", sort=False):
        row = {"zone": zone, "n": int(len(group))}
        for horizon in HORIZONS:
            values = group[f"ret_{horizon}d"].dropna()
            if values.empty:
                continue
            row[f"mean_{horizon}d"] = round(float(values.mean()), 2)
            row[f"median_{horizon}d"] = round(float(values.median()), 2)
            row[f"win_rate_{horizon}d"] = round(float((values > 0).mean()) * 100, 1)
        rows.append(row)

    order = {label: index for index, (_, label) in enumerate(ZONE_BUCKETS)}
    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary
    return summary.sort_values("zone", key=lambda s: s.map(order))


def summarize_drawdowns(metrics: pd.DataFrame) -> pd.DataFrame:
    """Per-zone worst in-window drawdown (negative %, lower is worse)."""
    rows = []
    for zone, group in metrics.groupby("zone", sort=False):
        row = {"zone": zone, "n": int(len(group))}
        for horizon in DRAWDOWN_HORIZONS:
            values = group[f"dd_{horizon}d"].dropna()
            if values.empty:
                continue
            row[f"mean_dd_{horizon}d"] = round(float(values.mean()), 2)
            row[f"median_dd_{horizon}d"] = round(float(values.median()), 2)
            row[f"worst_dd_{horizon}d"] = round(float(values.min()), 2)
        rows.append(row)

    order = {label: index for index, (_, label) in enumerate(ZONE_BUCKETS)}
    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary
    return summary.sort_values("zone", key=lambda s: s.map(order))


def independent_validation(
    metrics: pd.DataFrame,
    klines: pd.DataFrame,
    n_resamples: int = 2000,
) -> None:
    """Report non-overlapping, bootstrapped stats for every zone.

    Daily scores overlap heavily (3312 days are ~37 independent 90d cycles),
    so this section re-samples each zone at `horizon`-day spacing and wraps
    mean/win-rate in a 95% percentile-bootstrap interval.
    """
    print(f"\n=== Independent-sample validation (bootstrap 95% CI, {n_resamples} resamples) ===")
    print("Non-overlapping picks; wide CIs on thin zones are the honest picture.")

    rows = []
    for zone, group in metrics.groupby("zone", sort=False):
        dates = pd.DatetimeIndex(group["date"])
        for horizon in INDEPENDENT_HORIZONS:
            indep = sample_independent(dates, horizon)
            returns = forward_return(klines, indep, horizon).dropna()
            if returns.empty:
                continue
            mean_lo, mean_hi = bootstrap_ci(returns, np.mean, n_resamples)
            win_lo, win_hi = bootstrap_ci(
                returns, lambda x: float((x > 0).mean()) * 100, n_resamples
            )
            rows.append(
                {
                    "zone": zone,
                    "horizon": f"{horizon}d",
                    "n": len(returns),
                    "mean_ret": f"{returns.mean():.1f}% [{mean_lo:.1f}, {mean_hi:.1f}]",
                    "win_rate": (
                        f"{float((returns > 0).mean()) * 100:.1f}%"
                        f" [{win_lo:.1f}, {win_hi:.1f}]"
                    ),
                }
            )

    table = pd.DataFrame(rows)
    order = {label: index for index, (_, label) in enumerate(ZONE_BUCKETS)}
    if not table.empty:
        table = table.sort_values("zone", key=lambda s: s.map(order))
        print(table.to_string(index=False))


def episode_validation(
    metrics: pd.DataFrame,
    klines: pd.DataFrame,
    n_resamples: int = 2000,
) -> None:
    """Validate each zone on one return per consecutive-day run.

    Daily scores conflate days with episodes (109 negative days are only 23
    runs), so this section uses one observation per run. Besides bootstrap
    CIs it reports an exact one-sided binomial test (H0: win rate >= 50%,
    i.e. no negative edge) and a Bayesian posterior probability that the
    true win rate is below 50%, which stays interpretable on tiny samples.
    """
    print("\n=== Episode-level validation (1 return per run) ===")
    print("Each consecutive-day run counts once, not each day.")

    stats_rows = []
    evidence_rows = []
    dd_rows = []
    for zone, group in metrics.groupby("zone", sort=False):
        dates = _episode_first_dates(group)
        for horizon in INDEPENDENT_HORIZONS:
            returns = forward_return(klines, dates, horizon).dropna()
            if returns.empty:
                continue
            n = int(len(returns))
            wins = int((returns > 0).sum())
            mean_lo, mean_hi = bootstrap_ci(returns, np.mean, n_resamples)
            win_lo, win_hi = bootstrap_ci(
                returns, lambda x: float((x > 0).mean()) * 100, n_resamples
            )
            exact_p = _binomial_cdf(wins, n)
            bayes_p_neg = _binomial_cdf(wins, n + 1)
            prob_mean_neg = _probability_mean_negative(returns, n_resamples)

            stats_rows.append(
                {
                    "zone": zone,
                    "horizon": f"{horizon}d",
                    "ep": n,
                    "mean_ret": f"{returns.mean():.1f}% [{mean_lo:.1f}, {mean_hi:.1f}]",
                    "win_rate": (
                        f"{float((returns > 0).mean()) * 100:.1f}%"
                        f" [{win_lo:.1f}, {win_hi:.1f}]"
                    ),
                }
            )
            evidence_rows.append(
                {
                    "zone": zone,
                    "horizon": f"{horizon}d",
                    "ep": n,
                    "wins": f"{wins}/{n}",
                    "exact_p": f"{exact_p:.3f}",
                    "P_mean_neg": f"{prob_mean_neg:.0%}",
                    "P_win_neg": f"{bayes_p_neg:.0%}",
                }
            )

        for horizon in DRAWDOWN_HORIZONS:
            drawdowns = forward_max_drawdown(klines, dates, horizon).dropna()
            if drawdowns.empty:
                continue
            dd_lo, dd_hi = bootstrap_ci(drawdowns, np.mean, n_resamples)
            dd_rows.append(
                {
                    "zone": zone,
                    "horizon": f"{horizon}d",
                    "ep": len(drawdowns),
                    "mean_dd": (
                        f"{drawdowns.mean():.1f}% [{dd_lo:.1f}, {dd_hi:.1f}]"
                    ),
                    "worst_dd": f"{drawdowns.min():.1f}%",
                }
            )

    order = {label: index for index, (_, label) in enumerate(ZONE_BUCKETS)}
    stats_df = pd.DataFrame(stats_rows)
    if not stats_df.empty:
        stats_df = stats_df.sort_values("zone", key=lambda s: s.map(order))
        print("\n--- Stats per episode ---")
        print(stats_df.to_string(index=False))

    evidence_df = pd.DataFrame(evidence_rows)
    if not evidence_df.empty:
        evidence_df = evidence_df.sort_values("zone", key=lambda s: s.map(order))
        print("\n--- Evidence (small p_exact supports a negative edge) ---")
        print("exact_p: one-sided binomial test, H0 win rate >= 50%")
        print("P_mean_neg: bootstrap probability that episode mean return < 0")
        print("P_win_neg: Bayesian P(true win rate < 50%), Beta(1+w, 1+l)")
        print(evidence_df.to_string(index=False))

        neg = evidence_df[evidence_df["zone"] == "Selling zone"]
        if not neg.empty:
            print("\nBest-supported negative signal (Selling zone, by P_mean_neg):")
            best = neg.loc[(
                neg["P_mean_neg"].replace("%", "", regex=True).astype(float).idxmax()
            )]
            print(
                f"- {best['horizon']}: {best['wins']} winning episodes, "
                f"P(mean<0)={best['P_mean_neg']}, exact p={best['exact_p']} "
                f"(H0 win>=50%), Bayesian P(win<50%)={best['P_win_neg']}"
            )

    dd_df = pd.DataFrame(dd_rows)
    if not dd_df.empty:
        dd_df = dd_df.sort_values("zone", key=lambda s: s.map(order))
        print("\n--- Max drawdown per episode (worst peak-to-trough in-window) ---")
        print("mean_dd: average worst decline from a peak inside the window")
        print(dd_df.to_string(index=False))


def run_backtest(
    csv_path: str | None = None,
    independent: bool = False,
    resamples: int = 2000,
) -> pd.DataFrame:
    db = DatabaseManager()
    metrics = db.load_metrics_history()
    if metrics.empty:
        logger.error("No scored metrics found; run the score backfill first")
        return pd.DataFrame()

    metrics["date"] = pd.to_datetime(metrics["date"])
    if "zone" not in metrics.columns or metrics["zone"].isna().all():
        metrics["zone"] = _bucket(
            pd.to_numeric(metrics["total_score"], errors="coerce")
        )
        logger.info("No zone stored; inferred zones from total_score")

    klines = _load_klines(db)
    if klines.empty:
        logger.error("No BTC klines found; run the BTC backfill first")
        return pd.DataFrame()

    for horizon in HORIZONS:
        forward = forward_return(
            klines, pd.DatetimeIndex(metrics["date"]), horizon
        )
        metrics[f"ret_{horizon}d"] = forward.to_numpy()

    for horizon in DRAWDOWN_HORIZONS:
        drawdowns = forward_max_drawdown(
            klines, pd.DatetimeIndex(metrics["date"]), horizon
        )
        metrics[f"dd_{horizon}d"] = drawdowns.to_numpy()

    summary = summarize(metrics)
    dd_summary = summarize_drawdowns(metrics)

    print("\n=== Forward returns by score zone ===")
    if summary.empty:
        print("No data to summarize")
    else:
        print(summary.to_string(index=False))
        print("\nInterpretation:")
        for _, row in summary.iterrows():
            print(
                f"- {row['zone']} (n={int(row['n'])}): "
                f"mean 90d={row.get('mean_90d')}% "
                f"(win rate {row.get('win_rate_90d')}%)"
            )

    corr = metrics.dropna(subset=["total_score", "ret_90d"])
    if len(corr) >= 10:
        correlation = corr["total_score"].corr(corr["ret_90d"])
        print(f"\nCorrelation score vs 90d forward return: {correlation:.3f}")

    print("\n=== Forward max drawdown by zone (worst peak-to-trough in-window) ===")
    if dd_summary.empty:
        print("No data to summarize")
    else:
        print(dd_summary.to_string(index=False))
        print("\nReturns measure the end-line; drawdown measures the journey:")
        neg_zone = dd_summary[dd_summary["zone"] == "Selling zone"]
        high_zone = dd_summary[dd_summary["zone"] == "High accumulation zone"]
        for horizon in DRAWDOWN_HORIZONS:
            if neg_zone.empty or high_zone.empty:
                continue
            col = f"mean_dd_{horizon}d"
            n_mean = float(neg_zone[col].iloc[0])
            h_mean = float(high_zone[col].iloc[0])
            print(
                f"- At {horizon}d the Selling zone bottoms out at a mean "
                f"{n_mean:.1f}% below its peak vs {h_mean:.1f}% for High "
                f"accumulation: the zone is about avoiding the crash, "
                f"not about the 365d end-line."
            )

    if independent:
        independent_validation(metrics, klines, n_resamples=resamples)
        episode_validation(metrics, klines, n_resamples=resamples)

    if csv_path:
        metrics.to_csv(csv_path, index=False)
        logger.info(f"Backtest details saved to {csv_path}")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate the accumulation score with forward returns"
    )
    parser.add_argument(
        "--csv", help="Optional CSV path to store the per-day details"
    )
    parser.add_argument(
        "--independent",
        action="store_true",
        help="Also run the non-overlapping bootstrap validation",
    )
    parser.add_argument(
        "--resamples",
        type=int,
        default=2000,
        help="Bootstrap resamples for the independent validation (default 2000)",
    )
    args = parser.parse_args()
    run_backtest(csv_path=args.csv, independent=args.independent, resamples=args.resamples)