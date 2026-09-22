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

    _COMPONENTS = ("ema_200", "m2", "fear_greed", "rsi", "dxy")

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

    def _component_scores(self, **kwargs) -> dict[str, float]:
        return {
            "ema_200": self._score_ema_200(
                kwargs.get("current_price") or 0.0, kwargs.get("ema_200") or 0.0
            ),
            "m2": self._score_m2(float(kwargs.get("m2_yoy") or 0.0)),
            "fear_greed": self._score_fear_greed(
                float(kwargs.get("fear_greed") or 50.0)
            ),
            "rsi": self._score_rsi(float(kwargs.get("rsi") or 50.0)),
            "dxy": self._score_dxy(kwargs.get("dxy_status")),
        }

    @staticmethod
    def _classify(score: float) -> str:
        if score >= 80:
            return "Zona de Acumulación Alta"
        if score >= 60:
            return "Zona de Acumulación Moderada"
        if score >= 40:
            return "Zona Neutra"
        return "Zona a Evitar"

    def calculate(
        self,
        current_price: float,
        ema_200: float,
        rsi: float,
        fear_greed: float,
        m2_yoy: float,
        dxy_status: str,
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
        )

        score = sum(components[key] * self.weights[key] for key in components)
        score = int(round(_clip(score)))

        logger.info(
            f"Score components: "
            + ", ".join(f"{key}={components[key]:.0f}" for key in components)
            + f" -> total {score}/100 ({self._classify(score)})"
        )
        return {"score": score, "zone": self._classify(score)}