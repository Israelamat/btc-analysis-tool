import time

import pandas as pd
import requests

from src.fetchers.base import BaseFetcher
from src.utils.logger import setup_logger

logger = setup_logger()

TREND_LOOKBACK_DAYS = 5
YAHOO_HOSTS = (
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
)
MAX_ATTEMPTS = 3


class StockIndicesFetcher(BaseFetcher):
    """Connector for major US stock indices and the US dollar index (DXY).

    Uses the Yahoo Finance chart endpoint (free, no API key required).
    """

    BASE_URL = "https://{host}/v8/finance/chart"

    TICKERS = {
        "SP500": "^GSPC",
        "NASDAQ": "^IXIC",
        "DXY": "DX-Y.NYB",
    }

    def fetch_data(
        self, symbol: str, interval: str = "1d", range_period: str = "1mo"
    ) -> dict | None:
        """Fetch the chart payload for a single Yahoo Finance symbol."""
        last_error = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            for host in YAHOO_HOSTS:
                url = self.BASE_URL.format(host=host)
                try:
                    response = self._make_request(
                        f"{url}/{symbol}",
                        params={"range": range_period, "interval": interval},
                    )
                    result = (response.get("chart") or {}).get("result") or []
                    if result:
                        return result[0]
                except requests.exceptions.RequestException as e:
                    last_error = e
                    logger.warning(
                        f"Yahoo [{host}/{symbol}] attempt {attempt} failed: {e}"
                    )
            time.sleep(min(attempt * 2, 6))

        logger.error(f"Failed to fetch symbol [{symbol}] from Yahoo Finance: {last_error}")
        return None

    @staticmethod
    def _latest_close(chart: dict) -> float | None:
        """Extract the latest non-null close from a chart payload."""
        closes = (
            (chart.get("indicators") or {})
            .get("quote", [{}])[0]
            .get("close") or []
        )
        valid = [value for value in closes if value is not None]
        return float(valid[-1]) if valid else None

    @staticmethod
    def _trend(chart: dict) -> str:
        """Classify the short-term trend from the latest closes."""
        closes = (
            (chart.get("indicators") or {})
            .get("quote", [{}])[0]
            .get("close") or []
        )
        valid = [value for value in closes if value is not None]
        if len(valid) < TREND_LOOKBACK_DAYS + 1:
            return "neutral"

        latest = valid[-1]
        reference = valid[-(TREND_LOOKBACK_DAYS + 1)]
        change_pct = (latest / reference - 1) * 100

        if change_pct > 0.5:
            return "bullish"
        if change_pct < -0.5:
            return "bearish"
        return "neutral"

    def get_major_indices(self) -> dict:
        """Return SP500 and NASDAQ latest closes plus DXY short-term trend.

        Uses neutral/None defaults when a source cannot be fetched.
        """
        result = {"SP500": None, "NASDAQ": None, "DXY_trend": "neutral"}

        for key, symbol in self.TICKERS.items():
            chart = self.fetch_data(symbol)
            if chart is None:
                continue

            latest_close = self._latest_close(chart)
            if key == "DXY":
                result["DXY_trend"] = self._trend(chart)
            elif latest_close is not None:
                result[key] = round(latest_close, 2)

        logger.info(
            f"Stocks: SP500={result['SP500']} NASDAQ={result['NASDAQ']} "
            f"DXY_trend={result['DXY_trend']}"
        )
        return result

    @staticmethod
    def _history_chart(chart: dict) -> pd.Series:
        """Extract timestamp-aligned closes as a Series indexed by date."""
        timestamps = chart.get("timestamp") or []
        closes = (
            (chart.get("indicators") or {})
            .get("quote", [{}])[0]
            .get("close") or []
        )
        if not timestamps or not closes:
            return pd.Series(dtype="float64")
        dates = pd.to_datetime(timestamps, unit="s")
        series = pd.Series(closes, index=dates, dtype="float64")
        series = series[series.notna()]
        series.index = series.index.date
        return series[~series.index.duplicated(keep="last")]

    def get_history(self, range_period: str = "1y") -> pd.DataFrame:
        """Return aligned daily closes for SP500, NASDAQ and DXY.

        :param range_period: Yahoo Finance lookback, e.g. "1y" or "2y"
        :return: DataFrame with date, sp500, nasdaq and dxy columns
        """
        frames = {}
        for key, symbol in self.TICKERS.items():
            chart = self.fetch_data(symbol, range_period=range_period)
            if chart is None:
                logger.warning(f"No history chart for [{symbol}]")
                continue
            series = self._history_chart(chart)
            if series.empty:
                logger.warning(f"No closes in history for [{symbol}]")
                continue
            series.name = key
            frames[key] = series

        if not frames:
            logger.warning("No stock index history fetched")
            return pd.DataFrame(columns=["date", "sp500", "nasdaq", "dxy"])

        df = pd.DataFrame(frames)
        df.index.name = "date"
        df = df.astype(float).round(2).reset_index()
        logger.info(f"Fetched {len(df)} stock index daily rows (incl. DXY)")
        return df