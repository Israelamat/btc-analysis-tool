import numpy as np
import pandas as pd
import pytest

from src.analytics.indicators import (
    _rsi,
    _rsi_series,
    calculate_indicator_series,
    calculate_technical_indicators,
)


def _frame(n: int, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    closes = start + np.arange(n) * step
    return pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=n, freq="D"),
            "close": closes,
        }
    )


def test_indicator_series_respects_warmup_periods():
    out = calculate_indicator_series(_frame(400))

    assert out["rsi_14"].iloc[:14].isna().all()
    assert out["rsi_14"].iloc[14:].notna().all()
    assert out["sma_365"].iloc[:364].isna().all()
    assert out["sma_365"].iloc[364:].notna().all()
    assert out["mvrv"].iloc[364:].notna().all()
    assert out["nupl"].iloc[364:].notna().all()


def test_rsi_of_a_flat_series_is_neutral():
    flat = pd.Series([100.0] * 40)

    assert _rsi(flat) == pytest.approx(50.0)
    assert _rsi_series(flat).dropna().eq(50.0).all()


def test_single_day_indicators_are_missing_without_warmup():
    missing = calculate_technical_indicators(
        pd.DataFrame(columns=["date", "close"])
    )
    assert missing == {
        "latest_price": 0.0,
        "latest_date": None,
        "ema_200": 0.0,
        "rsi": 50.0,
        "macd_hist": 0.0,
    }

    short = calculate_technical_indicators(_frame(5))
    assert short["rsi"] == 50.0
    assert short["latest_price"] == pytest.approx(104.0)
