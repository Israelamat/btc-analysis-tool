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

SCORE_BIN_EDGES = tuple(range(0, 101, 10))

NOISE_THRESHOLD = 0.05


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


def _pearson(left: pd.Series, right: pd.Series) -> float | None:
    """Correlation rounded to 3 decimals, or None when it is undefined."""
    if len(left) < 3:
        return None
    value = left.corr(right)
    return None if value != value else round(float(value), 3)


def _quartile_means(values: pd.Series, forward: pd.Series) -> list[dict]:
    """Mean forward return per quartile of the sub-score, lowest first.

    Returns an empty list when the sub-score has no spread to cut on, which
    happens with a saturated component.
    """
    try:
        bins = pd.qcut(values, 4, labels=False, duplicates="drop")
    except ValueError:
        return []
    if not isinstance(bins, pd.Series):
        bins = pd.Series(bins, index=values.index)

    grouped = forward.groupby(bins, observed=True)
    out = []
    for position, (label, subset) in enumerate(grouped, start=1):
        out.append(
            {
                "quartile": position,
                "n": int(len(subset)),
                "mean": round(float(subset.mean()), 1),
            }
        )
    return out


def _verdict(pearson: float | None) -> str:
    """Plain-language reading of one component correlation."""
    if pearson is None:
        return "no_data"
    if abs(pearson) < NOISE_THRESHOLD:
        return "noise"
    return "positive" if pearson > 0 else "negative"


def load_scored_metrics(db: DatabaseManager | None = None) -> pd.DataFrame:
    """Stored scores joined with their 90d forward return, ready to calibrate.

    :param db: database to read; a default handle is created when omitted
    :return: metrics frame with a `ret_90d` column, or an empty frame when
        the score or kline tables are missing
    """
    db = db or DatabaseManager()
    metrics = db.load_metrics_history()
    if metrics.empty:
        logger.error("No scored metrics found; run the score backfill first")
        return pd.DataFrame()

    metrics["date"] = pd.to_datetime(metrics["date"])
    klines = _load_klines(db)
    if klines.empty:
        logger.error("No BTC klines found; run the BTC backfill first")
        return pd.DataFrame()

    dates = pd.DatetimeIndex(metrics["date"])
    metrics["ret_90d"] = forward_return(klines, dates, HORIZON).to_numpy()
    return metrics


def collect_calibration(metrics: pd.DataFrame) -> dict:
    """Structured version of the calibration report.

    A useful component is one whose 0-100 sub-score correlates positively with
    the forward return, which is what justifies its weight in `SCORE_WEIGHTS`.

    :param metrics: frame with a `ret_90d` column and a stored `components` blob
    :return: dict with the per-component correlation, its quartile breakdown and
        reading, the score binned by 10s, and the total-score correlation
    """
    if metrics is None or metrics.empty or "ret_90d" not in metrics.columns:
        return {
            "horizon_days": HORIZON,
            "sample": {"start": None, "end": None, "days": 0},
            "components": [],
            "score_bins": [],
            "total_score_pearson": None,
        }

    comps = _component_matrix(metrics)
    joined = (
        metrics[["date", "total_score", "ret_90d"]].join(comps).dropna(subset=["ret_90d"])
    )

    if joined.empty:
        return {
            "horizon_days": HORIZON,
            "sample": {"start": None, "end": None, "days": 0},
            "components": [],
            "score_bins": [],
            "total_score_pearson": None,
        }

    forward = joined["ret_90d"]
    components = []
    for key in COMPONENTS:
        if key not in joined.columns:
            continue
        pearson = _pearson(joined[key], forward)
        components.append(
            {
                "key": key,
                "pearson": pearson,
                "verdict": _verdict(pearson),
                "quartiles": _quartile_means(joined[key], forward),
            }
        )
    components.sort(key=lambda item: (item["pearson"] is None, -(item["pearson"] or 0)))

    bins = pd.cut(joined["total_score"], bins=list(SCORE_BIN_EDGES) + [101], right=False)
    grouped = joined.groupby(bins, observed=True)
    score_bins = [
        {
            "bin": f"{int(interval.left)}-{int(interval.right) - 1}",
            "n": int(len(subset)),
            "mean": round(float(subset["ret_90d"].mean()), 1),
            "median": round(float(subset["ret_90d"].median()), 1),
            "win_rate": round(_win_rate(subset["ret_90d"]), 1),
        }
        for interval, subset in grouped
    ]

    return {
        "horizon_days": HORIZON,
        "sample": {
            "start": joined["date"].min().strftime("%Y-%m-%d"),
            "end": joined["date"].max().strftime("%Y-%m-%d"),
            "days": int(len(joined)),
        },
        "components": components,
        "score_bins": score_bins,
        "total_score_pearson": _pearson(joined["total_score"], forward),
    }


def analyze() -> None:
    report = collect_calibration(load_scored_metrics())
    sample = report["sample"]
    if not sample["days"]:
        print("No scored metrics with a 90d forward return; nothing to calibrate")
        return

    print(
        f"=== Component score vs {report['horizon_days']}d fwd return "
        f"(n={sample['days']}, {sample['start']} to {sample['end']}) ==="
    )
    print("higher comp score should mean higher future return")
    for item in report["components"]:
        print(f"{item['key']:14s} pearson={item['pearson']:+.3f}  [{item['verdict']}]")

    print("\n=== Per-component quartiles: mean 90d ret ===")
    for item in report["components"]:
        parts = " ".join(f"Q{q['quartile']}: {q['mean']:+.1f}" for q in item["quartiles"])
        if parts:
            print(f"{item['key']:14s} {parts}")

    print("\n=== Score binned by 10s ===")
    print(pd.DataFrame(report["score_bins"]).to_string(index=False))

    print(
        f"\nTotal score vs {report['horizon_days']}d return: "
        f"pearson={report['total_score_pearson']:+.3f}"
    )


if __name__ == "__main__":
    analyze()