import pandas as pd
import requests

from src.fetchers.base import BaseFetcher
from src.utils.logger import setup_logger

logger = setup_logger()

KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
]

OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def _empty_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the expected OHLCV columns."""
    return pd.DataFrame(columns=OHLCV_COLUMNS)


def _rows_to_frame(rows: list) -> pd.DataFrame:
    """Convert raw Binance klines into a clean OHLCV DataFrame.

    Binance returns one kline per row as a fixed-length list; only the
    first six elements (time, OHLC, volume) are used.
    """
    if not rows:
        logger.warning("No klines received from Binance")
        return _empty_frame()

    df = pd.DataFrame(rows).iloc[:, :6]
    df.columns = KLINE_COLUMNS
    df["date"] = pd.to_datetime(df["open_time"], unit="ms").dt.date
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    if df["close"].isna().all():
        logger.warning("BTC klines contain no close prices")
        return _empty_frame()

    return df[OHLCV_COLUMNS]


class BTCFetcher(BaseFetcher):
    """Connector for Binance public spot API."""

    BASE_URL = "https://api.binance.com/api/v3/klines"

    def fetch_data(
        self, symbol: str = "BTCUSDT", interval: str = "1d", limit: int = 250
    ) -> list:
        """Fetch raw klines from Binance.

        :param symbol: Trading pair, e.g. BTCUSDT
        :param interval: Kline interval, e.g. 1d
        :param limit: Number of klines to fetch
        :return: List of klines as returned by Binance
        """
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        try:
            response = self._make_request(self.BASE_URL, params=params)
        except requests.exceptions.RequestException:
            logger.error("Failed to fetch BTC klines from Binance")
            return []

        if isinstance(response, list) and response:
            return response

        logger.warning("Unexpected Binance response format")
        return []

    def get_daily_klines(self, limit: int = 250) -> pd.DataFrame:
        """Return daily OHLCV data as a pandas DataFrame.

        :param limit: Number of daily candles to fetch
        :return: DataFrame with columns date, open, high, low, close, volume
        """
        data = self.fetch_data(limit=limit)
        df = _rows_to_frame(data)
        if df.empty:
            logger.warning("Returning empty DataFrame (no BTC data available)")
            return df

        logger.info(
            f"Fetched {len(df)} daily candles for BTC up to {df['date'].iloc[-1]}"
        )
        return df

    def get_full_history(self, chunk: int = 1000) -> pd.DataFrame:
        """Return the complete BTC/USDT daily history from Binance.

        Binance caps each request at ``chunk`` candles, so the history is
        paginated with ``startTime`` until all candles are retrieved.

        :param chunk: Max candles per request (Binance cap is 1000)
        :return: DataFrame with columns date, open, high, low, close, volume
        """
        rows = []
        start_time = 0
        while True:
            params = {
                "symbol": "BTCUSDT",
                "interval": "1d",
                "limit": chunk,
                "startTime": start_time,
            }
            try:
                response = self._make_request(self.BASE_URL, params=params)
            except requests.exceptions.RequestException:
                logger.error("Failed to fetch BTC full history from Binance")
                break

            if not isinstance(response, list) or not response:
                break

            rows.extend(response)
            if len(response) < chunk:
                break
            start_time = int(response[-1][0]) + 1

        df = _rows_to_frame(rows)
        if df.empty:
            logger.warning("Returning empty DataFrame (no BTC full history)")
            return df

        logger.info(
            f"Fetched {len(df)} daily candles for BTC up to {df['date'].iloc[-1]}"
        )
        return df