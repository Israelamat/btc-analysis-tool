import pytest

from src.analytics.scoring import BTCAcumulationScorer
from src.config import Config


def test_weights_are_empirical_and_normalized():
    weights = Config.SCORE_WEIGHTS
    assert set(weights) == set(BTCAcumulationScorer._COMPONENTS)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert all(weight > 0 for weight in weights.values())
    assert weights["proxy_mvrv"] == pytest.approx(0.25)
    assert weights["proxy_nupl"] == pytest.approx(0.15)


def test_macd_component_no_longer_saturates_on_normal_readings():
    scorer = BTCAcumulationScorer()
    score = scorer._score_macd(0.1, 100.0)
    assert score == pytest.approx(70.0)
    assert 0.0 < score < 100.0
    assert scorer._score_macd(-0.1, 100.0) == pytest.approx(30.0)


def test_missing_weighted_signal_renormalizes_and_reports_coverage():
    result = BTCAcumulationScorer().calculate(
        current_price=100.0,
        ema_200=100.0,
        rsi=30.0,
        fear_greed=0.0,
        m2_yoy=None,
        dxy_status="neutral",
        macd_hist=0.0,
        google_trends=50.0,
        proxy_mvrv=1.0,
        proxy_nupl=0.0,
    )

    assert result["missing"] == ["m2"]
    assert result["coverage"] == pytest.approx(
        1 - Config.SCORE_WEIGHTS["m2"]
    )
    assert result["low_confidence"] is False
    assert result["score"] == 55


def test_low_coverage_caps_a_strong_call():
    scorer = BTCAcumulationScorer()

    strong_buy = scorer.calculate(
        current_price=None,
        ema_200=None,
        rsi=0.0,
        fear_greed=0.0,
        m2_yoy=None,
        dxy_status=None,
    )
    assert strong_buy["raw_zone"] == "High accumulation zone"
    assert strong_buy["zone"] == "Moderate accumulation zone"
    assert strong_buy["coverage"] == pytest.approx(0.10)
    assert strong_buy["low_confidence"] is True

    strong_sell = scorer.calculate(
        current_price=None,
        ema_200=None,
        rsi=70.0,
        fear_greed=100.0,
        m2_yoy=None,
        dxy_status=None,
    )
    assert strong_sell["raw_zone"] == "Selling zone"
    assert strong_sell["zone"] == "Neutral zone"
    assert strong_sell["low_confidence"] is True
