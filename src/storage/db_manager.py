import os
import sqlite3
import pandas as pd
from src.config import Config


class DatabaseManager:

    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics_history (
                    date TEXT PRIMARY KEY,
                    btc_price REAL,
                    ema_200 REAL,
                    rsi_14 REAL,
                    fear_greed INTEGER,
                    m2_yoy REAL,
                    sp500 REAL,
                    nasdaq REAL,
                    total_score REAL
                )
            """
            )
            conn.commit()

    def save_daily_metrics(self, data: dict):
        """Save metrics data to the database."""
        query = """
            INSERT INTO metrics_history (date, btc_price, ema_200, rsi_14, fear_greed, m2_yoy, sp500, nasdaq, total_score)
            VALUES (:date, :btc_price, :ema_200, :rsi_14, :fear_greed, :m2_yoy, :sp500, :nasdaq, :total_score)
            ON CONFLICT(date) DO UPDATE SET
                btc_price=excluded.btc_price,
                ema_200=excluded.ema_200,
                rsi_14=excluded.rsi_14,
                fear_greed=excluded.fear_greed,
                m2_yoy=excluded.m2_yoy,
                sp500=excluded.sp500,
                nasdaq=excluded.nasdaq,
                total_score=excluded.total_score;
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, data)
            conn.commit()

    def load_latest_metrics(self, limit: int = 30) -> pd.DataFrame:
        with self._get_connection() as conn:
            query = f"SELECT * FROM metrics_history ORDER BY date DESC LIMIT {limit}"
            return pd.read_sql_query(query, conn)