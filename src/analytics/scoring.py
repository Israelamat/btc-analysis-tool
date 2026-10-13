import math

from src.config import Config
from src.utils.logger import setup_logger

logger = setup_logger()


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _present(value) -> bool:
    """True when a raw signal value is usable (not None / NaN)."""
    if value is None:
        return False
    try:
        return not math.isnan(float(value))
    except (TypeError, ValueError):
        return False


class BTCAcumulationScorer:
    """Scores how attractive BTC accumulation looks right now (0-100)."""

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights if weights is not None else dict(Config.SCORE_WEIGHTS)
        missing = [key for key in self.weights if key not in self._COMPONENTS]
        self.weights = {
            key: weight
            for key, weight in self.weights.items()
            if key in self._COMPONENTS
        }
        self.weights = self._normalize(self.weights)
        if missing:
            logger.warning(
                f"Ignoring unknown score weights: {missing}"
            )

    _COMPONENTS = ("ema_200", "m2", "fear_greed", "rsi", "dxy", "macd", "google_trends")

    @staticmethod
    def _normalize(weights: dict[str, float]) -> dict[str, float]:
        total = sum(weights.values()) or 1.0
        return {key: value / total for key, value in weights.items()}

    @staticmethod
    def _score_ema_200(current_price: float, ema_200: float) -> float:
        """Price below EMA200 => cheaper => better for accumulation (contrarian).

        Gradual slope (3x per percentage point) and a soft clamp avoid the
        score saturating to 0/100 during normal bull/bear swings, keeping
        the weight sensitive.
        """
        if not ema_200:
            return 50.0
        distance_pct = (current_price / ema_200 - 1) * 100
        return _clip(50 - distance_pct * 3, 5.0, 95.0)

    @staticmethod
    def _score_rsi(rsi: float) -> float:
        """Oversold (low RSI) => good entry, overbought (high RSI) => avoid."""
        return _clip((70 - rsi) / 40 * 100)

    @staticmethod
    def _score_fear_greed(value: float) -> float:
        """Extreme fear => 100, extreme greed => 0."""
        return _clip(100 - value)

    @staticmethod
    def _score_m2(m2_yoy: float) -> float:
        """Growing money supply => more liquidity => bullish for BTC."""
        return _clip(m2_yoy / 8 * 100)

    @staticmethod
    def _score_dxy(dxy_status: str | None) -> float:
        """Weak dollar tends to support BTC."""
        status = (dxy_status or "neutral").lower()
        if status == "bearish":
            return 100.0
        if status == "bullish":
            return 0.0
        return 50.0

    @staticmethod
    def _score_macd(macd_hist: float, current_price: float) -> float:
        """Positive histogram relative to price => bullish momentum."""
        if not current_price:
            return 50.0
        pct = (macd_hist / current_price) * 100
        return _clip(50 + pct * 200)

    @staticmethod
    def _score_google_trends(value: float) -> float:
        """High search interest => retail euphoria => contrarian penalty."""
        return _clip(100 - value)

    def _component_scores(self, **kwargs) -> dict[str, float]:
        """Score only the signals that are actually available.

        A signal is missing when its raw value is None/NaN; a missing signal is
        left out of the dict so :meth:`calculate` can renormalize over the
        available weights instead of feeding it a fabricated neutral value.
        """
        scores: dict[str, float] = {}
        price = kwargs.get("current_price")
        has_price = _present(price) and float(price) > 0

        ema_200 = kwargs.get("ema_200")
        if has_price and _present(ema_200) and float(ema_200) > 0:
            scores["ema_200"] = self._score_ema_200(float(price), float(ema_200))

        macd_hist = kwargs.get("macd_hist")
        if has_price and _present(macd_hist):
            scores["macd"] = self._score_macd(float(macd_hist), float(price))

        if _present(kwargs.get("m2_yoy")):
            scores["m2"] = self._score_m2(float(kwargs["m2_yoy"]))
        if _present(kwargs.get("fear_greed")):
            scores["fear_greed"] = self._score_fear_greed(
                float(kwargs["fear_greed"])
            )
        if _present(kwargs.get("rsi")):
            scores["rsi"] = self._score_rsi(float(kwargs["rsi"]))
        dxy_status = kwargs.get("dxy_status")
        if isinstance(dxy_status, str) and dxy_status:
            scores["dxy"] = self._score_dxy(dxy_status)
        if _present(kwargs.get("google_trends")):
            scores["google_trends"] = self._score_google_trends(
                float(kwargs["google_trends"])
            )
        return scores

    @staticmethod
    def _classify(score: float) -> str:
        if score >= 70:
            return "High accumulation zone"
        if score >= 50:
            return "Moderate accumulation zone"
        if score >= 30:
            return "Neutral zone"
        return "Selling zone"

    @staticmethod
    def _cap_zone(zone: str) -> str:
        """Softest allowed zone when the coverage is too low to trust.

        Keeps the strongest calls (High accumulation, Selling) out of reach
        when too little of the signal weight is available.
        """
        if zone == "High accumulation zone":
            return "Moderate accumulation zone"
        if zone == "Selling zone":
            return "Neutral zone"
        return zone

    def calculate(
        self,
        current_price: float | None,
        ema_200: float | None,
        rsi: float | None,
        fear_greed: float | None,
        m2_yoy: float | None,
        dxy_status: str | None,
        macd_hist: float | None = None,
        google_trends: float | None = None,
    ) -> dict:
        """Calculate the accumulation score and its zone.

        Missing signals (None/NaN) are dropped and the weights renormalized
        over what is available, so the score never goes dark because one source
        failed. ``coverage`` reports the share of the weight that was actually
        used; below ``Config.COVERAGE_MIN`` the zone is capped (High ->
        Moderate, Selling -> Neutral) and ``low_confidence`` is set.

        :return: dict with 'score' (int, 0-100), 'zone' (str, after the cap),
            'raw_zone' (str, before the cap), 'components' (available per-signal
            scores, 0-100), 'missing' (list), 'coverage' (0-1) and
            'low_confidence' (bool)
        """
        components = self._component_scores(
            current_price=current_price,
            ema_200=ema_200,
            rsi=rsi,
            fear_greed=fear_greed,
            m2_yoy=m2_yoy,
            dxy_status=dxy_status,
            macd_hist=macd_hist,
            google_trends=google_trends,
        )

        missing = [key for key in self._COMPONENTS if key not in components]
        coverage = sum(self.weights[key] for key in components)
        if components and coverage > 0:
            weighted = sum(
                components[key] * self.weights[key] for key in components
            )
            raw_score = weighted / coverage
        else:
            raw_score = 50.0
        score = int(round(_clip(raw_score)))

        raw_zone = self._classify(score)
        low_confidence = coverage < Config.COVERAGE_MIN
        zone = self._cap_zone(raw_zone) if low_confidence else raw_zone

        logger.info(
            f"Score components: "
            + ", ".join(f"{key}={components[key]:.0f}" for key in components)
            + f" -> total {score}/100 ({zone}) "
            + f"[coverage={coverage:.2f}"
            + (f", missing={','.join(missing)}" if missing else "")
            + (", low_confidence" if low_confidence else "")
            + "]"
        )
        return {
            "score": score,
            "zone": zone,
            "raw_zone": raw_zone,
            "components": {key: round(value, 1) for key, value in components.items()},
            "missing": missing,
            "coverage": round(coverage, 3),
            "low_confidence": low_confidence,
        }