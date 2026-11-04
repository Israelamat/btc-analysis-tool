import numpy as np
import pandas as pd
import pytest

from src.analytics.backtest import (
    CYCLE_HORIZONS,
    build_parser,
    correlation_table,
    cycle_playbook_table,
    episode_evidence_table,
    forward_max_drawdown,
    forward_return,
    monthly_dca_table,
    summarize,
    temporal_correlation_table,
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


def test_cycle_summary_reports_365_and_730_columns():
    metrics = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "zone": "High accumulation zone",
            "total_score": [80.0, 60.0],
            "ret_365d": [100.0, 50.0],
            "ret_730d": [200.0, 100.0],
        }
    )

    table = summarize(metrics, CYCLE_HORIZONS)

    assert table.iloc[0]["mean_365d"] == pytest.approx(75.0)
    assert table.iloc[0]["mean_730d"] == pytest.approx(150.0)
    assert table.iloc[0]["win_rate_730d"] == pytest.approx(100.0)


def test_correlation_table_covers_each_requested_horizon():
    score = pd.Series(np.linspace(0, 100, 30))
    metrics = pd.DataFrame(
        {
            "total_score": score,
            "ret_365d": score * 2,
            "ret_730d": score * 3,
        }
    )

    table = correlation_table(metrics, (365, 730))

    assert table["horizon"].tolist() == ["365d", "730d"]
    assert table["pearson"].tolist() == pytest.approx([1.0, 1.0])


def test_temporal_stability_splits_before_and_after():
    dates = pd.date_range("2020-01-01", periods=40, freq="30D")
    score = pd.Series(np.arange(len(dates)) % 10, dtype=float)
    metrics = pd.DataFrame(
        {
            "date": dates,
            "total_score": score,
            "ret_365d": score * 2,
            "ret_730d": score * 3,
        }
    )

    table = temporal_correlation_table(
        metrics, split="2022-01-01", horizons=(365, 730)
    )

    assert set(table["period"]) == {"before_split", "after_split"}
    assert set(table["horizon"]) == {"365d", "730d"}
    assert len(table) == 4


def test_monthly_dca_uses_prior_score_and_lowers_cost():
    metrics = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]
            ),
            "btc_price": [100.0, 50.0, 100.0, 100.0],
            "total_score": [100.0, 0.0, 0.0, 0.0],
        }
    )

    row = monthly_dca_table(metrics).iloc[0]

    assert row["months"] == 4
    assert row["flat_avg_cost"] == pytest.approx(80.0)
    assert row["scaled_avg_cost"] == pytest.approx(70.0)
    assert row["cost_improvement_pct"] > 0


def test_cycle_playbook_pairs_high_with_next_selling():
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    klines = pd.DataFrame(
        {"close": [100, 100, 100, 120, 120, 120, 110, 110, 110, 121]},
        index=dates,
    )
    metrics = pd.DataFrame(
        {
            "date": [dates[0], dates[3], dates[6]],
            "zone": [
                "High accumulation zone",
                "Selling zone",
                "High accumulation zone",
            ],
        }
    )

    table = cycle_playbook_table(metrics, klines)

    realized = table[table["state"] == "Realized"].iloc[0]
    unrealized = table[table["state"] == "Unrealized"].iloc[0]
    assert realized["trades"] == 1
    assert realized["win_rate_pct"] == pytest.approx(100.0)
    assert realized["mean_return_pct"] == pytest.approx(20.0)
    assert unrealized["trades"] == 1
    assert unrealized["mean_return_pct"] == pytest.approx(10.0)


def test_parser_exposes_long_term_flag():
    args = build_parser().parse_args(["--long-term"])

    assert args.long_term is True
    assert args.independent is False


def test_parser_combines_long_term_and_independent():
    args = build_parser().parse_args(["--long-term", "--independent"])

    assert args.long_term is True
    assert args.independent is True
