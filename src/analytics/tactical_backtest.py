"""Evaluate whether a 90-day tactical score improves monthly DCA.

Builds a few transparent candidates from the calibrated features, compares
their forward-return separation and simulates a monthly DCA whose
contribution is modulated between 0.5x and 1.5x. The existing cycle score is
included as the baseline overlay.
"""

import numpy as np
import pandas as pd

from src.analytics.tactical_features import build_tactical_panel, monthly_panel
from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

HORIZON = 90
BASE_CONTRIBUTION = 1000.0
MULTIPLIER_MIN = 0.5
MULTIPLIER_MAX = 1.5
TARGET = f"fwd_{HORIZON}d"

CANDIDATES = {
    "deriv_contrarian": (
        ("funding_pct", -1.0, 0.35),
        ("basis_pct", -1.0, 0.35),
        ("delta_pct", 1.0, 0.30),
    ),
    "sentiment_momentum": (
        ("fg_pct", 1.0, 0.34),
        ("rsi_pct", 1.0, 0.33),
        ("trends_pct", 1.0, 0.33),
    ),
    "combined": (
        ("funding_pct", -1.0, 0.15),
        ("basis_pct", -1.0, 0.15),
        ("delta_pct", 1.0, 0.20),
        ("fg_pct", 1.0, 0.20),
        ("rsi_pct", 1.0, 0.15),
        ("trends_pct", 1.0, 0.15),
    ),
}


def add_candidate_scores(panel: pd.DataFrame) -> pd.DataFrame:
    """Add each candidate score (0-100) to the panel, no look-ahead."""
    frame = panel.copy()
    for name, specs in CANDIDATES.items():
        score = pd.Series(0.0, index=frame.index)
        total_weight = 0.0
        for column, sign, weight in specs:
            series = frame[column]
            component = series if sign > 0 else 100.0 - series
            score = score.add(component * weight, fill_value=0.0)
            total_weight += weight
        frame[name] = score / total_weight if total_weight else np.nan

    frame["trends_contrarian"] = 100.0 - frame["google_trends"]
    frame["cycle"] = frame["cycle_score"]
    return frame


def score_columns(frame: pd.DataFrame) -> list[str]:
    return list(CANDIDATES) + ["trends_contrarian", "cycle"]


def _spearman(frame: pd.DataFrame, feature: str, target: str) -> float:
    sample = frame[[feature, target]].dropna()
    if len(sample) < 10:
        return np.nan
    ranked = sample.rank()
    return float(ranked[feature].corr(ranked[target]))


def forward_separation(
    monthly: pd.DataFrame, scores: list[str]
) -> pd.DataFrame:
    """IC and top/bottom tercile spread of each candidate at monthly samples."""
    rows = []
    for score in scores:
        sample = monthly[[score, TARGET]].dropna()
        if len(sample) < 20:
            continue
        try:
            buckets = pd.qcut(sample[score], 3, labels=False, duplicates="drop")
        except ValueError:
            continue
        high = sample.loc[buckets == buckets.max(), TARGET].mean()
        low = sample.loc[buckets == buckets.min(), TARGET].mean()
        rows.append(
            {
                "score": score,
                "n": len(sample),
                "ic": round(_spearman(monthly, score, TARGET), 3),
                "top_tercile_ret": round(float(high), 1),
                "bottom_tercile_ret": round(float(low), 1),
                "spread": round(float(high - low), 1),
            }
        )
    return pd.DataFrame(rows)


def _dca_path(
    sample: pd.DataFrame, multiplier: pd.Series
) -> dict:
    """Simulate monthly buys at the sample close and mark to the last close."""
    prices = sample["spot_close"].to_numpy(dtype=float)
    contributions = BASE_CONTRIBUTION * multiplier.to_numpy(dtype=float)
    units = contributions / prices
    cumulative_units = np.cumsum(units)
    invested = np.cumsum(contributions)
    value = cumulative_units * prices
    path = value / np.maximum.accumulate(value) - 1.0
    total_units = cumulative_units[-1]
    total_invested = invested[-1]
    final_value = total_units * prices[-1]
    return {
        "months": int(len(sample)),
        "invested": float(total_invested),
        "units": float(total_units),
        "avg_cost": float(total_invested / total_units),
        "final_value": float(final_value),
        "roi_pct": float((final_value / total_invested - 1.0) * 100),
        "max_dd_pct": float(path.min() * 100),
    }


def dca_comparison(monthly: pd.DataFrame, scores: list[str]) -> pd.DataFrame:
    """Modulated DCA vs flat DCA over the same monthly dates."""
    rows = []
    for score in scores:
        sample = monthly[["date", "spot_close", score]].dropna().sort_values("date")
        if len(sample) < 12:
            continue
        score = sample[score].clip(0, 100)
        multiplier = MULTIPLIER_MIN + (
            (MULTIPLIER_MAX - MULTIPLIER_MIN) * score / 100.0
        )
        tactical = _dca_path(sample, multiplier)
        flat = _dca_path(sample, pd.Series(1.0, index=sample.index))
        rows.append(
            {
                "score": score.name,
                "months": tactical["months"],
                "avg_multiplier": round(float(multiplier.mean()), 2),
                "tactical_avg_cost": round(tactical["avg_cost"], 0),
                "flat_avg_cost": round(flat["avg_cost"], 0),
                "cost_improvement_pct": round(
                    (flat["avg_cost"] / tactical["avg_cost"] - 1) * 100, 2
                ),
                "tactical_roi": round(tactical["roi_pct"], 1),
                "flat_roi": round(flat["roi_pct"], 1),
                "tactical_dd": round(tactical["max_dd_pct"], 1),
                "flat_dd": round(flat["max_dd_pct"], 1),
            }
        )
    return pd.DataFrame(rows)


def subperiod_ic(
    monthly: pd.DataFrame, scores: list[str]
) -> pd.DataFrame:
    periods = (
        ("2019-2021", "2019-01-01", "2022-01-01"),
        ("2022-2024", "2022-01-01", "2024-01-01"),
        ("2024+", "2024-01-01", "2100-01-01"),
    )
    rows = []
    for score in scores:
        row = {"score": score}
        for name, start, end in periods:
            sample = monthly[
                (monthly["date"] >= start) & (monthly["date"] < end)
            ]
            row[name] = round(_spearman(sample, score, TARGET), 3)
        rows.append(row)
    return pd.DataFrame(rows)


def run_tactical_backtest() -> tuple[pd.DataFrame, pd.DataFrame]:
    db = DatabaseManager()
    panel = add_candidate_scores(build_tactical_panel(db))
    if panel.empty:
        logger.error("Tactical panel is empty; run the derivatives backfill")
        return pd.DataFrame(), pd.DataFrame()

    monthly = monthly_panel(panel).dropna(subset=["spot_close"])
    scores = score_columns(panel)

    print(f"\n=== Tactical score evaluation (90d, {len(monthly)} monthly samples) ===")
    separation = forward_separation(monthly.dropna(subset=[TARGET]), scores)
    print(separation.to_string(index=False))

    print("\n=== 90d forward IC by subperiod (monthly samples) ===")
    print(subperiod_ic(monthly.dropna(subset=[TARGET]), scores).to_string(index=False))

    print("\n=== Monthly DCA with 0.5x-1.5x modulation ===")
    dca = dca_comparison(monthly, scores)
    print(dca.to_string(index=False))
    print(
        "cost_improvement_pct > 0 means the overlay bought at a lower average "
        "cost than flat DCA over the same months."
    )
    return separation, dca


if __name__ == "__main__":
    run_tactical_backtest()
