import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")
    DB_PATH: str = os.getenv("DB_PATH", "data/macro_crypto.db")
    START_DATE: str = os.getenv("START_DATE", "2017-08-01")

    SCORE_WEIGHTS = {
        "proxy_mvrv": 0.25,
        "proxy_nupl": 0.15,
        "google_trends": 0.12,
        "fear_greed": 0.05,
        "macd": 0.13,
        "ema_200": 0.10,
        "rsi": 0.05,
        "dxy": 0.10,
        "m2": 0.05,
    }

    # Minimum share of the total weight that must be available for the score to
    # be trusted. Below it the zone is capped (High -> Moderate, Selling ->
    # Neutral) so a couple of weak signals cannot label a strong buy or sell.
    COVERAGE_MIN: float = float(os.getenv("COVERAGE_MIN", "0.5"))

    # Symmetric 0-100 transform shared by the accumulation score and the
    # /api/valuation display: the ratio that maps to the neutral 50, and the
    # span (ratio units) from the center to saturation at 0/100.
    VALUATION_RATIO_CENTER: float = float(os.getenv("VALUATION_RATIO_CENTER", "1.0"))
    VALUATION_RATIO_SPAN: float = float(os.getenv("VALUATION_RATIO_SPAN", "0.3"))

    # Neutral anchor and span-to-saturation for the proxy NUPL transform
    # (same symmetric 0-100 mapping used for the valuation ratio).
    NUPL_CENTER: float = float(os.getenv("NUPL_CENTER", "0.0"))
    NUPL_SPAN: float = float(os.getenv("NUPL_SPAN", "0.4"))