"""Validate the accumulation score against forward BTC returns.

For every day with a recorded score, computes the BTC return over the
following 7/30/90 calendar days and groups it by score zone, so the
contrarian "buy when cheap" hypothesis can be checked empirically.
"""

import argparse

import pandas as pd

from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

HORIZONS = (7, 30, 90)
ZONE_BUCKETS = (
    (70.0, "High accumulation zone"),
    (50.0, "Moderate accumulation zone"),
    (30.0, "Neutral zone"),
    (float("-inf"), "Not a good zone"),
)


def _bucket(score: pd.Series) -> pd.Series:
    """Map scores to the same zones used by the scorer."""
    out = pd.Series("Not a good zone", index=score.index, dtype="object")
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


def run_backtest(csv_path: str | None = None) -> pd.DataFrame:
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

    summary = summarize(metrics)

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
    args = parser.parse_args()
    run_backtest(csv_path=args.csv)