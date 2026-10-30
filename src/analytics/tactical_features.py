"""Derivatives-based features for the 90-day tactical score.

Every feature is computed with trailing windows only, so the panel can be
used as-of any date without look-ahead. Forward 90d returns/drawdowns are
added separately as targets for calibration and backtesting.
"""

import numpy as np
import pandas as pd

from src.analytics.backtest import forward_max_drawdown, forward_return
from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

PERCENTILE_WINDOW = 365
PERCENTILE_MIN = 180

PANEL_FEATURES = (
    "funding_7d",
    "funding_30d",
    "funding_pct",
    "basis",
    "basis_7d",
    "basis_30d",
    "basis_pct",
    "delta_7d",
    "delta_30d",
    "delta_pct",
    "ret_30d",
    "ret_90d",
    "ret_180d",
    "rsi_14",
    "rsi_pct",
    "fear_greed",
    "fg_pct",
    "google_trends",
    "trends_pct",
    "mvrv",
    "nupl",
    "drawdown_365",
    "cycle_score",
)


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stored frame to a unique, date-sorted index."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.sort_values("date").drop_duplicates("date", keep="last")


def trailing_percentile(
    series: pd.Series,
    window: int = PERCENTILE_WINDOW,
    min_periods: int = PERCENTILE_MIN,
) -> pd.Series:
    """Percentile (0-100) of the latest value inside its trailing window."""
    return series.rolling(window, min_periods=min_periods).apply(
        lambda values: float((values[-1] >= values).mean() * 100.0),
        raw=True,
    )


def _ffill_to(series: pd.Series, index: pd.DatetimeIndex, limit: int) -> pd.Series:
    if series.empty:
        return pd.Series(np.nan, index=index)
    return series.sort_index().reindex(index, method="ffill", limit=limit)


def build_tactical_panel(
    db: DatabaseManager, horizon: int = 90
) -> pd.DataFrame:
    """Join spot, derivatives and sentiment into one daily no-lookahead panel.

    The panel starts when USD-M futures data starts (2019-09). Percentile
    features need ``PERCENTILE_MIN`` days of history, so the score itself is
    usable from roughly 2020-Q2.
    """
    spot = _prepare(db.load_btc_klines())
    futures = _prepare(db.load_futures_klines())
    funding = _prepare(db.load_funding())
    indicators = _prepare(db.load_btc_indicators())
    fear_greed = _prepare(db.load_fear_greed())
    trends = _prepare(db.load_google_trends())
    metrics = _prepare(db.load_metrics_history())

    if spot.empty or futures.empty:
        logger.warning("Missing BTC spot/futures data; run the derivatives backfill")
        return pd.DataFrame()

    spot_indexed = spot.set_index("date")
    panel = futures.set_index("date").copy()
    index = pd.DatetimeIndex(panel.index)

    panel["spot_close"] = _ffill_to(spot_indexed["close"], index, limit=2)
    panel["basis"] = panel["close"] / panel["spot_close"] - 1.0

    funding_series = (
        funding.set_index("date")["funding_rate"] if not funding.empty else pd.Series()
    )
    panel["funding_rate"] = _ffill_to(funding_series, index, limit=2)

    volume = panel["volume"].replace(0, np.nan)
    panel["delta_7d"] = (
        panel["volume_delta"].rolling(7).sum() / volume.rolling(7).sum()
    )
    panel["delta_30d"] = (
        panel["volume_delta"].rolling(30).sum() / volume.rolling(30).sum()
    )
    panel["funding_7d"] = panel["funding_rate"].rolling(7).mean()
    panel["funding_30d"] = panel["funding_rate"].rolling(30).mean()
    panel["basis_7d"] = panel["basis"].rolling(7).mean()
    panel["basis_30d"] = panel["basis"].rolling(30).mean()

    panel["funding_pct"] = trailing_percentile(panel["funding_7d"])
    panel["basis_pct"] = trailing_percentile(panel["basis_30d"])
    panel["delta_pct"] = trailing_percentile(panel["delta_30d"])

    panel["ret_30d"] = (panel["spot_close"] / panel["spot_close"].shift(30) - 1) * 100
    panel["ret_90d"] = (panel["spot_close"] / panel["spot_close"].shift(90) - 1) * 100
    panel["ret_180d"] = (panel["spot_close"] / panel["spot_close"].shift(180) - 1) * 100
    rolling_peak = panel["spot_close"].rolling(365, min_periods=30).max()
    panel["drawdown_365"] = (panel["spot_close"] / rolling_peak - 1) * 100

    if not indicators.empty:
        ind = indicators.set_index("date")
        for column in ("rsi_14", "mvrv", "nupl"):
            if column in ind.columns:
                panel[column] = _ffill_to(ind[column], index, limit=7)
    if "rsi_14" in panel.columns:
        panel["rsi_pct"] = trailing_percentile(panel["rsi_14"])

    if not fear_greed.empty:
        panel["fear_greed"] = _ffill_to(
            fear_greed.set_index("date")["value"], index, limit=7
        )
        panel["fg_pct"] = trailing_percentile(panel["fear_greed"])

    if not trends.empty:
        panel["google_trends"] = _ffill_to(
            trends.set_index("date")["value"], index, limit=30
        )
        panel["trends_pct"] = trailing_percentile(panel["google_trends"])

    if not metrics.empty:
        panel["cycle_score"] = _ffill_to(
            metrics.set_index("date")["total_score"], index, limit=7
        )
        panel["cycle_zone"] = _ffill_to(
            metrics.set_index("date")["zone"], index, limit=7
        )

    panel = panel.reset_index()
    dates = pd.DatetimeIndex(panel["date"])
    panel[f"fwd_{horizon}d"] = forward_return(
        spot_indexed, dates, horizon
    ).to_numpy()
    panel[f"fwd_dd_{horizon}d"] = forward_max_drawdown(
        spot_indexed, dates, horizon
    ).to_numpy()

    return panel


def monthly_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """First available row of every month (reduces overlapping observations)."""
    if panel.empty:
        return panel
    frame = panel.set_index("date").sort_index()
    monthly = frame.resample("MS").first().dropna(subset=["spot_close"])
    return monthly.reset_index()
