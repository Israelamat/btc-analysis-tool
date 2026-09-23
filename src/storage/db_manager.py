import os
import sqlite3
import pandas as pd
from src.config import Config


class DatabaseManager:

    TABLE_NAMES = (
        "metrics_history",
        "btc_klines",
        "fear_greed_history",
        "fred_series",
        "google_trends",
        "stock_history",
        "btc_indicators",
    )

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
            cursor.executescript(
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
                    dxy TEXT,
                    macd_hist REAL,
                    google_trends REAL,
                    total_score REAL
                );

                CREATE TABLE IF NOT EXISTS btc_klines (
                    date TEXT PRIMARY KEY,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL
                );

                CREATE TABLE IF NOT EXISTS fear_greed_history (
                    date TEXT PRIMARY KEY,
                    value INTEGER,
                    classification TEXT
                );

                CREATE TABLE IF NOT EXISTS fred_series (
                    series_id TEXT,
                    date TEXT,
                    value REAL,
                    PRIMARY KEY (series_id, date)
                );

                CREATE TABLE IF NOT EXISTS google_trends (
                    keyword TEXT,
                    date TEXT,
                    value REAL,
                    PRIMARY KEY (keyword, date)
                );

                CREATE TABLE IF NOT EXISTS stock_history (
                    date TEXT PRIMARY KEY,
                    sp500 REAL,
                    nasdaq REAL,
                    dxy REAL
                );

                CREATE TABLE IF NOT EXISTS btc_indicators (
                    date TEXT PRIMARY KEY,
                    ema_200 REAL,
                    rsi_14 REAL,
                    macd REAL,
                    macd_signal REAL,
                    macd_hist REAL
                );
            """
            )
            columns = [row[1] for row in cursor.execute("PRAGMA table_info(metrics_history)")]
            for column, kind in (("dxy", "TEXT"), ("macd_hist", "REAL"), ("google_trends", "REAL")):
                if column not in columns:
                    cursor.execute(f"ALTER TABLE metrics_history ADD COLUMN {column} {kind}")
            conn.commit()

    def save_daily_metrics(self, data: dict):
        """Save metrics data to the database (upsert by date)."""
        query = """
            INSERT INTO metrics_history (date, btc_price, ema_200, rsi_14, fear_greed, m2_yoy, sp500, nasdaq, dxy, macd_hist, google_trends, total_score)
            VALUES (:date, :btc_price, :ema_200, :rsi_14, :fear_greed, :m2_yoy, :sp500, :nasdaq, :dxy, :macd_hist, :google_trends, :total_score)
            ON CONFLICT(date) DO UPDATE SET
                btc_price=excluded.btc_price,
                ema_200=excluded.ema_200,
                rsi_14=excluded.rsi_14,
                fear_greed=excluded.fear_greed,
                m2_yoy=excluded.m2_yoy,
                sp500=excluded.sp500,
                nasdaq=excluded.nasdaq,
                dxy=excluded.dxy,
                macd_hist=excluded.macd_hist,
                google_trends=excluded.google_trends,
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

    @staticmethod
    def _df_to_rows(df: pd.DataFrame, columns: tuple[str, ...]) -> list[tuple]:
        """Convert a DataFrame into a list of tuples, mapping NaNs to NULL."""
        if columns and set(df.columns).issubset(columns):
            frame = df[list(columns)]
        else:
            frame = df
        if "date" in frame.columns:
            frame = frame.copy()
            frame["date"] = frame["date"].astype(str)
        frame = frame.where(pd.notna(frame), None)
        return [tuple(row) for row in frame.itertuples(index=False, name=None)]

    def upsert_btc_klines(self, df: pd.DataFrame) -> int:
        """Upsert BTC daily klines into btc_klines, returning the row count."""
        if df is None or df.empty:
            return 0
        columns = ("date", "open", "high", "low", "close", "volume")
        rows = self._df_to_rows(df, columns)
        query = """
            INSERT INTO btc_klines (date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume;
        """
        with self._get_connection() as conn:
            conn.executemany(query, rows)
            conn.commit()
        return len(rows)

    def upsert_fear_greed(self, rows: list[dict]) -> int:
        """Upsert Fear & Greed history, returning the row count."""
        if not rows:
            return 0
        values = [
            (str(row["date"]), int(row["value"]), row.get("classification"))
            for row in rows
        ]
        query = """
            INSERT INTO fear_greed_history (date, value, classification)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                value=excluded.value, classification=excluded.classification;
        """
        with self._get_connection() as conn:
            conn.executemany(query, values)
            conn.commit()
        return len(values)

    def upsert_fred(self, series_id: str, rows: list[dict]) -> int:
        """Upsert FRED observations, returning the row count."""
        if not rows:
            return 0
        values = [
            (series_id, str(row["date"]), float(row["value"])) for row in rows
        ]
        query = """
            INSERT INTO fred_series (series_id, date, value)
            VALUES (?, ?, ?)
            ON CONFLICT(series_id, date) DO UPDATE SET value=excluded.value;
        """
        with self._get_connection() as conn:
            conn.executemany(query, values)
            conn.commit()
        return len(values)

    def upsert_google_trends(self, keyword: str, rows: list[dict]) -> int:
        """Upsert Google Trends interest, returning the row count."""
        if not rows:
            return 0
        values = [
            (keyword, str(row["date"]), float(row["value"])) for row in rows
        ]
        query = """
            INSERT INTO google_trends (keyword, date, value)
            VALUES (?, ?, ?)
            ON CONFLICT(keyword, date) DO UPDATE SET value=excluded.value;
        """
        with self._get_connection() as conn:
            conn.executemany(query, values)
            conn.commit()
        return len(values)

    def upsert_stock_history(self, df: pd.DataFrame) -> int:
        """Upsert aligned stock index history, returning the row count."""
        if df is None or df.empty:
            return 0
        columns = ("date", "sp500", "nasdaq", "dxy")
        rows = self._df_to_rows(df, columns)
        query = """
            INSERT INTO stock_history (date, sp500, nasdaq, dxy)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                sp500=excluded.sp500, nasdaq=excluded.nasdaq, dxy=excluded.dxy;
        """
        with self._get_connection() as conn:
            conn.executemany(query, rows)
            conn.commit()
        return len(rows)

    def upsert_btc_indicators(self, df: pd.DataFrame) -> int:
        """Upsert indicator series (EMA-200/RSI-14/MACD), returning the row count."""
        if df is None or df.empty:
            return 0
        columns = ("date", "ema_200", "rsi_14", "macd", "macd_signal", "macd_hist")
        rows = self._df_to_rows(df, columns)
        query = """
            INSERT INTO btc_indicators (date, ema_200, rsi_14, macd, macd_signal, macd_hist)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                ema_200=excluded.ema_200, rsi_14=excluded.rsi_14,
                macd=excluded.macd, macd_signal=excluded.macd_signal,
                macd_hist=excluded.macd_hist;
        """
        with self._get_connection() as conn:
            conn.executemany(query, rows)
            conn.commit()
        return len(rows)

    def load_btc_klines(self) -> pd.DataFrame:
        """Load all BTC daily klines ordered by date."""
        with self._get_connection() as conn:
            query = """
                SELECT date, open, high, low, close, volume
                FROM btc_klines
                ORDER BY date
            """
            return pd.read_sql_query(query, conn)

    def load_btc_indicators(self) -> pd.DataFrame:
        """Load all computed indicator series ordered by date."""
        with self._get_connection() as conn:
            query = "SELECT * FROM btc_indicators ORDER BY date"
            return pd.read_sql_query(query, conn)

    def load_fear_greed(self) -> pd.DataFrame:
        """Load the full Fear & Greed history."""
        with self._get_connection() as conn:
            query = "SELECT date, value, classification FROM fear_greed_history"
            return pd.read_sql_query(query, conn)

    def load_fred_series(self, series_id: str = "M2SL") -> pd.DataFrame:
        """Load a FRED series history."""
        with self._get_connection() as conn:
            query = "SELECT date, value FROM fred_series WHERE series_id = ? ORDER BY date"
            return pd.read_sql_query(query, conn, params=(series_id,))

    def load_stock_history(self) -> pd.DataFrame:
        """Load the aligned stock index history (SP500/NASDAQ/DXY)."""
        with self._get_connection() as conn:
            query = "SELECT date, sp500, nasdaq, dxy FROM stock_history ORDER BY date"
            return pd.read_sql_query(query, conn)

    def load_google_trends(self, keyword: str = "bitcoin") -> pd.DataFrame:
        """Load the Google Trends interest history for a keyword."""
        with self._get_connection() as conn:
            query = "SELECT date, value FROM google_trends WHERE keyword = ? ORDER BY date"
            return pd.read_sql_query(query, conn, params=(keyword,))

    def table_counts(self) -> dict:
        """Row count for every known table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            return {
                name: cursor.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in self.TABLE_NAMES
            }