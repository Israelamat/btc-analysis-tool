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
