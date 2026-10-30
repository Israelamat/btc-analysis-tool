import pandas as pd
import pytest

from src.storage.db_manager import DatabaseManager


def _row(date: str, score: float) -> dict:
    return {
        "date": date,
        "btc_price": 100.0,
        "ema_200": 90.0,
        "rsi_14": 45.0,
        "fear_greed": 50,
        "m2_yoy": 2.0,
        "sp500": 5000.0,
        "nasdaq": 15000.0,
        "dxy": "neutral",
        "macd_hist": 0.1,
        "google_trends": 40.0,
        "total_score": score,
        "zone": "Neutral zone",
        "components": "{}",
        "coverage": 1.0,
    }


def test_bulk_metrics_upsert(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))

    db.save_daily_metrics(_row("2024-01-01", 10))
    db.save_daily_metrics(_row("2024-01-02", 20))
    db.save_daily_metrics(_row("2024-01-01", 99))

    metrics = db.load_metrics_history()
    assert len(metrics) == 2
    row = metrics.loc[metrics["date"] == "2024-01-01"].iloc[0]
    assert row["total_score"] == pytest.approx(99.0)


def test_metrics_history_loads_in_date_order(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))
    for date, score in (("2024-01-03", 30), ("2024-01-01", 10), ("2024-01-02", 20)):
        db.save_daily_metrics(_row(date, score))

    metrics = db.load_metrics_history()
    assert metrics["date"].tolist() == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert metrics["total_score"].tolist() == [10.0, 20.0, 30.0]


def test_futures_and_funding_upserts(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))
    futures = [
        {
            "date": "2024-01-01",
            "close": 42000.0,
            "volume": 100.0,
            "quote_volume": 4_200_000.0,
            "taker_buy_base": 60.0,
            "taker_buy_quote": 2_520_000.0,
            "trades": 1000,
            "volume_delta": 20.0,
            "delta_ratio": 0.2,
        }
    ]
    funding = [
        {
            "date": "2024-01-01",
            "funding_rate": 0.0001,
            "funding_sum": 0.0003,
            "funding_count": 3,
        }
    ]

    assert db.upsert_futures_klines(pd.DataFrame(futures)) == 1
    assert db.upsert_funding(pd.DataFrame(funding)) == 1
    db.upsert_funding(pd.DataFrame(funding))  # idempotent

    loaded_futures = db.load_futures_klines()
    loaded_funding = db.load_funding()
    assert loaded_futures.iloc[0]["delta_ratio"] == pytest.approx(0.2)
    assert len(loaded_funding) == 1
    assert loaded_funding.iloc[0]["funding_count"] == 3
    assert db.table_counts()["futures_klines"] == 1
    assert db.table_counts()["funding_history"] == 1
