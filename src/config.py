import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")
    DB_PATH: str = os.getenv("DB_PATH", "data/macro_crypto.db")
    START_DATE: str = os.getenv("START_DATE", "2017-08-01")

    SCORE_WEIGHTS = {
        "google_trends": 0.60,
        "m2": 0.05,
        "macd": 0.16,
        "dxy": 0.10,
        "ema_200": 0.04,
        "rsi": 0.02,
        "fear_greed": 0.03,
    }

    # Minimum share of the total weight that must be available for the score to
    # be trusted. Below it the zone is capped (High -> Moderate, Selling ->
    # Neutral) so a couple of weak signals cannot label a strong buy or sell.
    COVERAGE_MIN: float = float(os.getenv("COVERAGE_MIN", "0.5"))