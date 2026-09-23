import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")
    DB_PATH: str = os.getenv("DB_PATH", "data/macro_crypto.db")
    START_DATE: str = os.getenv("START_DATE", "2017-08-01")

    SCORE_WEIGHTS = {
        "ema_200": 0.30,
        "m2": 0.20,
        "fear_greed": 0.20,
        "rsi": 0.15,
        "dxy": 0.15,
    }