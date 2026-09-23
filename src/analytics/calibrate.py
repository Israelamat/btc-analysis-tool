"""Analyze which score components actually predict forward BTC returns.

Helps recalibrate SCORE_WEIGHTS: a useful component should have a
positive correlation between its sub-score (0-100, higher = more
attractive to accumulate) and the forward return.
"""

import json

import pandas as pd

from src.analytics.backtest import _load_klines, forward_return
from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

COMPONENTS = ("ema_200", "m2", "fear_greed", "rsi", "dxy", "macd", "google_trends")
HORIZON = 90


def _component_matrix(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in metrics.iterrows():
        comps = row.get("components")
        if isinstance(comps, str):
            comps = json.loads(comps)
        rows.append(comps or {})
    return pd.DataFrame(rows, index=metrics.index)


def _win_rate(values: pd.Series) -> float:
    return float((values > 0).mean() * 100)


def analyze() -> None:
    db = DatabaseManager()
    metrics = db.load_metrics_history()
    if metrics.empty:
        logger.error("No scored metrics found; run the score backfill first")
        return

    metrics["date"] = pd.to_datetime(metrics["date"])
    klines = _load_klines(db)
    dates = pd.DatetimeIndex(metrics["date"])
    fwd = forward_return(klines, dates, HORIZON)
    metrics["ret_90d"] = fwd.to_numpy()

    comps = _component_matrix(metrics)
    joined = metrics[["total_score", "ret_90d"]].join(comps).dropna(subset=["ret_90d"])

    print(f"=== Component score vs {HORIZON}d fwd return (n={len(joined)}) ===")
    print("higher comp score should mean higher future return")
    rows = []
    for c in COMPONENTS:
        pear = joined[c].corr(joined["ret_90d"])
        rows.append((c, pear))
    for c, p in sorted(rows, key=lambda x: x[1], reverse=True):
        print(f"{c:14s} pearson={p:+.3f}")

    print("\n=== Per-component quartiles: mean 90d ret ===")
    for c in COMPONENTS:
        q = pd.qcut(joined[c], 4, labels=False, duplicates="drop")
        group = joined.groupby(q, observed=True)["ret_90d"]
        parts = " ".join(f"{k}: {v:+.1f}" for k, v in group.mean().items())
        print(f"{c:14s} {parts}")

    print("\n=== Score binned by 10s ===")
    buckets = pd.cut(joined["total_score"], bins=range(0, 101, 10), right=False)
    grouped = joined.groupby(buckets, observed=True).agg(
        n=("ret_90d", "size"),
        mean=("ret_90d", "mean"),
        median=("ret_90d", "median"),
        win_rate=("ret_90d", lambda x: _win_rate(x)),
    )
    print(grouped.round(1).to_string())

    corr = joined["total_score"].corr(joined["ret_90d"])
    print(f"\nTotal score vs {HORIZON}d return: pearson={corr:.3f}")


if __name__ == "__main__":
    analyze()