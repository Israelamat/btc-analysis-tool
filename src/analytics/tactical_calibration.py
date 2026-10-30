"""Calibration of the 90-day tactical features against forward BTC returns.

Prints univariate Spearman IC, decile spreads, subperiod stability and the
feature correlation matrix so the score is built from evidence instead of
prior beliefs. Run with ``python -m src.analytics.tactical_calibration``.
"""

import numpy as np
import pandas as pd

from src.analytics.tactical_features import (
    PANEL_FEATURES,
    build_tactical_panel,
    monthly_panel,
)
from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

TARGET = "fwd_90d"
SUBPERIODS = (
    ("2019-2021", "2019-01-01", "2022-01-01"),
    ("2022-2024", "2022-01-01", "2024-01-01"),
    ("2024+", "2024-01-01", "2100-01-01"),
)


def _spearman(frame: pd.DataFrame, feature: str, target: str) -> float:
    sample = frame[[feature, target]].dropna()
    if len(sample) < 10:
        return np.nan
    ranked = sample.rank()
    return float(ranked[feature].corr(ranked[target]))


def _decile_spread(frame: pd.DataFrame, feature: str, target: str) -> float:
    sample = frame[[feature, target]].dropna()
    if len(sample) < 20:
        return np.nan
    try:
        buckets = pd.qcut(sample[feature], 10, labels=False, duplicates="drop")
    except ValueError:
        return np.nan
    top = sample.loc[buckets == buckets.max(), target].mean()
    bottom = sample.loc[buckets == buckets.min(), target].mean()
    return float(top - bottom)


def feature_table(panel: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for feature in PANEL_FEATURES:
        if feature not in panel.columns:
            continue
        row = {
            "feature": feature,
            "n_daily": int(panel[[feature, TARGET]].dropna().shape[0]),
            "ic_daily": round(_spearman(panel, feature, TARGET), 3),
            "n_monthly": int(monthly[[feature, TARGET]].dropna().shape[0]),
            "ic_monthly": round(_spearman(monthly, feature, TARGET), 3),
            "decile_spread": round(_decile_spread(monthly, feature, TARGET), 1),
        }
        for name, start, end in SUBPERIODS:
            sample = monthly[
                (monthly["date"] >= start) & (monthly["date"] < end)
            ]
            row[f"ic_{name}"] = round(_spearman(sample, feature, TARGET), 3)
        rows.append(row)
    return pd.DataFrame(rows)


def correlation_matrix(monthly: pd.DataFrame) -> pd.DataFrame:
    columns = [c for c in PANEL_FEATURES if c in monthly.columns]
    return monthly[columns].rank().corr().round(2)


def run_calibration() -> tuple[pd.DataFrame, pd.DataFrame]:
    db = DatabaseManager()
    panel = build_tactical_panel(db)
    if panel.empty:
        logger.error("Tactical panel is empty; run the derivatives backfill")
        return pd.DataFrame(), pd.DataFrame()

    monthly = monthly_panel(panel).dropna(subset=[TARGET])
    if monthly.empty:
        logger.error("No complete 90d forward windows available")
        return pd.DataFrame(), pd.DataFrame()

    print(
        f"\n=== Tactical features vs {TARGET} "
        f"(panel {panel['date'].min().date()} -> {panel['date'].max().date()}) ==="
    )
    print(f"Monthly samples: {len(monthly)} | target mean {monthly[TARGET].mean():.1f}%")
    table = feature_table(panel, monthly)
    print(table.to_string(index=False))

    print("\n=== Spearman correlation matrix (monthly) ===")
    matrix = correlation_matrix(monthly)
    print(matrix.to_string())

    print("\n=== Cycle score vs tactical features ===")
    for feature in PANEL_FEATURES:
        if feature in monthly.columns and feature != "cycle_score":
            corr = _spearman(monthly, feature, "cycle_score")
            print(f"- {feature}: {corr:.3f}")

    return table, matrix


if __name__ == "__main__":
    run_calibration()
