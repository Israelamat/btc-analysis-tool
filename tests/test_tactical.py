import pandas as pd
import pytest

from src.analytics.tactical_backtest import _dca_path
from src.analytics.tactical_features import trailing_percentile
from src.fetchers.binance_futures import funding_rows_to_frame, kline_rows_to_frame


def _kline(open_time: int, close: float, volume: float, taker_buy: float) -> list:
    return [
        open_time,
        "1",
        "2",
        "0.5",
        str(close),
        str(volume),
        open_time + 86_399_999,
        "0",
        10,
        str(taker_buy),
        "0",
    ]


def test_futures_kline_delta_is_taker_buy_minus_sell():
    rows = [
        _kline(1_700_000_000_000, 100.0, 10.0, 7.0),
        _kline(1_700_086_400_000, 110.0, 10.0, 2.0),
    ]

    frame = kline_rows_to_frame(rows)

    assert len(frame) == 2
    assert frame["volume_delta"].tolist() == [4.0, -6.0]
    assert frame["delta_ratio"].tolist() == [0.4, -0.6]
    assert frame["date"].iloc[0] == pd.Timestamp("2023-11-14").date()


def test_funding_rows_are_aggregated_by_day():
    day = 1_700_006_400_000
    rows = [
        {"fundingTime": day, "fundingRate": "0.0001"},
        {"fundingTime": day + 8 * 3_600_000, "fundingRate": "0.0003"},
        {"fundingTime": day + 16 * 3_600_000, "fundingRate": "-0.0002"},
    ]

    frame = funding_rows_to_frame(rows)

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["funding_count"] == 3
    assert row["funding_sum"] == pytest.approx(0.0002)
    assert row["funding_rate"] == pytest.approx(0.0002 / 3)


def test_trailing_percentile_does_not_look_ahead():
    series = pd.Series([1.0, 2.0, 3.0, 4.0])

    first = trailing_percentile(series, window=3, min_periods=1)

    extended = pd.concat([series, pd.Series([100.0])], ignore_index=True)
    second = trailing_percentile(extended, window=3, min_periods=1)

    assert first.tolist() == second.iloc[: len(first)].tolist()
    assert first.iloc[2] == 100.0


def test_dca_path_buys_monthly_and_marks_to_last_close():
    sample = pd.DataFrame(
        {"spot_close": [100.0, 200.0], "date": ["2024-01-01", "2024-02-01"]}
    )

    result = _dca_path(sample, pd.Series([1.0, 1.0]))

    assert result["units"] == 15.0
    assert result["invested"] == 2000.0
    assert result["final_value"] == 3000.0
    assert result["avg_cost"] == pytest.approx(2000 / 15)
    assert result["roi_pct"] == pytest.approx(50.0)
    assert result["max_dd_pct"] == 0.0


def test_dca_path_drawdown_is_measured_on_portfolio_value():
    sample = pd.DataFrame(
        {"spot_close": [100.0, 50.0], "date": ["2024-01-01", "2024-02-01"]}
    )

    result = _dca_path(sample, pd.Series([1.0, 0.0]))

    assert result["max_dd_pct"] == pytest.approx(-50.0)
