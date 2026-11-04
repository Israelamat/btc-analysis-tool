from src.analytics.backtest import ZONE_BUCKETS
from src.analytics.chart import HIGH_ZONE, SELLING_ZONE, TABLE_HORIZONS


def test_chart_zones_match_backtest_thresholds():
    thresholds = {label: score for score, label in ZONE_BUCKETS}

    assert HIGH_ZONE == thresholds["High accumulation zone"]
    assert SELLING_ZONE == thresholds["Neutral zone"]


def test_chart_table_includes_cycle_horizons():
    assert 365 in TABLE_HORIZONS
    assert 730 in TABLE_HORIZONS
