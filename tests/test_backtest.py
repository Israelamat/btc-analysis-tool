import numpy as np
import pandas as pd
import pytest

from src.analytics.backtest import (
    episode_evidence_table,
    forward_max_drawdown,
    forward_return,
)


def _klines(
    n: int = 120, start: float = 100.0, step: float = 1.0
) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"close": start + np.arange(n) * step}, index=index
    )


def test_forward_return_requires_full_horizon():
    klines = _klines(30)

    assert forward_return(
        klines, pd.DatetimeIndex(["2024-01-20"]), 30
    ).isna().all()

    valid = forward_return(klines, pd.DatetimeIndex(["2024-01-01"]), 29)
    assert valid.iloc[0] == pytest.approx((129 / 100 - 1) * 100)


def test_forward_return_does_not_ffill_past_last_candle():
    klines = _klines(30)

    assert forward_return(
        klines, pd.DatetimeIndex(["2024-01-26"]), 10
    ).isna().all()

    inside = forward_return(klines, pd.DatetimeIndex(["2024-01-20"]), 10)
    assert not np.isnan(inside.iloc[0])


def test_forward_max_drawdown_requires_full_window():
    klines = _klines(30, start=300.0, step=-5.0)

    assert forward_max_drawdown(
        klines, pd.DatetimeIndex(["2024-01-20"]), 30
    ).isna().all()

    drawdown = forward_max_drawdown(
        klines, pd.DatetimeIndex(["2024-01-01"]), 29
    )
    assert drawdown.iloc[0] == pytest.approx((155 / 300 - 1) * 100)


def test_episode_evidence_win_probability_points_the_right_way():
    metrics = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-10", "2024-06-10"]),
            "zone": "High accumulation zone",
        }
    )
    rising = _klines(400, start=100.0, step=1.0)
    falling = _klines(400, start=600.0, step=-1.0)

    wins = episode_evidence_table(metrics, rising, n_resamples=500)
    losses = episode_evidence_table(metrics, falling, n_resamples=500)

    p_win = float(wins["P_win_neg"].iloc[0].rstrip("%")) / 100
    p_loss = float(losses["P_win_neg"].iloc[0].rstrip("%")) / 100

    assert p_win < 0.5 < p_loss
