from src.config import Config
from src.utils.logger import setup_logger

logger = setup_logger()


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


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
    def _num(value, default: float) -> float:
        try:
            number = float(value)
            return default if number != number else number
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize(weights: dict[str, float]) -> dict[str, float]:
        total = sum(weights.values()) or 1.0
        return {key: value / total for key, value in weights.items()}

    @staticmethod
    def _score_ema_200(current_price: float, ema_200: float) -> float:
        """Price below EMA200 => cheaper => better for accumulation."""
        if not ema_200:
            return 50.0
        distance_pct = (current_price / ema_200 - 1) * 100
        return _clip(100 - distance_pct * 10)

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
        return {
            "ema_200": self._score_ema_200(
                self._num(kwargs.get("current_price"), 0.0),
                self._num(kwargs.get("ema_200"), 0.0),
            ),
            "m2": self._score_m2(self._num(kwargs.get("m2_yoy"), 0.0)),
            "fear_greed": self._score_fear_greed(
                self._num(kwargs.get("fear_greed"), 50.0)
            ),
            "rsi": self._score_rsi(self._num(kwargs.get("rsi"), 50.0)),
            "dxy": self._score_dxy(kwargs.get("dxy_status")),
            "macd": self._score_macd(
                self._num(kwargs.get("macd_hist"), 0.0),
                self._num(kwargs.get("current_price"), 0.0),
            ),
            "google_trends": self._score_google_trends(
                self._num(kwargs.get("google_trends"), 50.0)
            ),
        }

    @staticmethod
    def _classify(score: float) -> str:
        if score >= 80:
            return " High accumation zone"
        if score >= 60:
            return "Moderate accumulation zone"
        if score >= 40:
            return "Neutral zone"
        return "Not a good zone"

    def calculate(
        self,
        current_price: float,
        ema_200: float,
        rsi: float,
        fear_greed: float,
        m2_yoy: float,
        dxy_status: str,
        macd_hist: float = 0.0,
        google_trends: float = 50.0,
    ) -> dict:
        """Calculate the accumulation score and its zone.

        :return: dict with 'score' (int, 0-100) and 'zone' (str)
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

        score = sum(components[key] * self.weights[key] for key in components)
        score = int(round(_clip(score)))

        logger.info(
            f"Score components: "
            + ", ".join(f"{key}={components[key]:.0f}" for key in components)
            + f" -> total {score}/100 ({self._classify(score)})"
        )
        return {"score": score, "zone": self._classify(score)}