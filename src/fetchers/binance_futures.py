from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

from src.fetchers.base import BaseFetcher
from src.utils.logger import setup_logger

logger = setup_logger()

FUTURES_BASE_URL = "https://fapi.binance.com"
# Binance treats startTime=0 on fundingRate as "latest page", so pagination
# starts before the BTCUSDT perpetual listing (2019-09-08) instead.
FUNDING_START_MS = int(datetime(2019, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
KLINE_URL = f"{FUTURES_BASE_URL}/fapi/v1/klines"
FUNDING_URL = f"{FUTURES_BASE_URL}/fapi/v1/fundingRate"

KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
]

FUTURES_COLUMNS = [
    "date",
    "close",
    "volume",
    "quote_volume",
    "taker_buy_base",
    "taker_buy_quote",
    "trades",
    "volume_delta",
    "delta_ratio",
]

FUNDING_COLUMNS = ["date", "funding_rate", "funding_sum", "funding_count"]


def _empty_futures() -> pd.DataFrame:
    return pd.DataFrame(columns=FUTURES_COLUMNS)


def _empty_funding() -> pd.DataFrame:
    return pd.DataFrame(columns=FUNDING_COLUMNS)


def kline_rows_to_frame(rows: list) -> pd.DataFrame:
    """Convert raw Binance futures klines into daily features.

    ``volume_delta`` is the taker buy/sell imbalance in base units
    (``2 * taker_buy_base - volume``) and ``delta_ratio`` normalizes it to
    [-1, 1], a daily proxy for cumulative volume delta.
    """
    if not rows:
        logger.warning("No futures klines received from Binance")
        return _empty_futures()

    frame = pd.DataFrame(rows).iloc[:, : len(KLINE_COLUMNS)]
    frame.columns = KLINE_COLUMNS
    frame["date"] = (
        pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        .dt.tz_localize(None)
        .dt.normalize()
        .dt.date
    )
    numeric = [
        "close",
        "volume",
        "quote_volume",
        "taker_buy_base",
        "taker_buy_quote",
        "trades",
    ]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["volume_delta"] = 2 * frame["taker_buy_base"] - frame["volume"]
    frame["delta_ratio"] = np.where(
        frame["volume"] > 0,
        frame["volume_delta"] / frame["volume"],
        0.0,
    )
    frame = frame.dropna(subset=["close"])
    return frame[FUTURES_COLUMNS]


def funding_rows_to_frame(rows: list) -> pd.DataFrame:
    """Aggregate the 8h funding prints into one row per UTC day."""
    if not rows:
        logger.warning("No funding history received from Binance")
        return _empty_funding()

    frame = pd.DataFrame(rows)
    frame["date"] = (
        pd.to_datetime(frame["fundingTime"], unit="ms", utc=True)
        .dt.tz_localize(None)
        .dt.normalize()
        .dt.date
    )
    frame["funding_rate"] = pd.to_numeric(frame["fundingRate"], errors="coerce")
    frame = frame.dropna(subset=["funding_rate"])

    grouped = (
        frame.groupby("date", as_index=False)
        .agg(
            funding_rate=("funding_rate", "mean"),
            funding_sum=("funding_rate", "sum"),
            funding_count=("funding_rate", "size"),
        )
        .sort_values("date")
    )
    return grouped[FUNDING_COLUMNS]


class BinanceFuturesFetcher(BaseFetcher):
    """Connector for Binance USD-M futures (funding, klines, flow)."""

    def fetch_data(
        self, symbol: str = "BTCUSDT", interval: str = "1d", limit: int = 1500
    ) -> list:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        try:
            response = self._make_request(KLINE_URL, params=params)
        except requests.exceptions.RequestException:
            logger.error("Failed to fetch Binance futures klines")
            return []
        return response if isinstance(response, list) else []

    def get_daily_klines(
        self, symbol: str = "BTCUSDT", chunk: int = 1500
    ) -> pd.DataFrame:
        """Paginate the full USD-M futures daily history."""
        rows: list = []
        start_time = 0
        while True:
            params = {
                "symbol": symbol,
                "interval": "1d",
                "limit": chunk,
                "startTime": start_time,
            }
            try:
                response = self._make_request(KLINE_URL, params=params)
            except requests.exceptions.RequestException:
                logger.error("Failed to fetch futures kline history")
                break
            if not isinstance(response, list) or not response:
                break
            rows.extend(response)
            if len(response) < chunk:
                break
            start_time = int(response[-1][0]) + 1

        frame = kline_rows_to_frame(rows)
        if not frame.empty:
            logger.info(
                f"Fetched {len(frame)} futures daily candles "
                f"up to {frame['date'].iloc[-1]}"
            )
        return frame

    def get_recent_funding(
        self, symbol: str = "BTCUSDT", limit: int = 10
    ) -> pd.DataFrame:
        """Fetch only the latest funding prints (fetcher smoke tests)."""
        try:
            response = self._make_request(
                FUNDING_URL, params={"symbol": symbol, "limit": limit}
            )
        except requests.exceptions.RequestException:
            logger.error("Failed to fetch recent funding rates")
            return _empty_funding()
        return funding_rows_to_frame(response if isinstance(response, list) else [])

    def get_funding_history(
        self, symbol: str = "BTCUSDT", chunk: int = 1000
    ) -> pd.DataFrame:
        """Paginate the full funding-rate history and aggregate it daily."""
        rows: list = []
        start_time = FUNDING_START_MS
        while True:
            params = {"symbol": symbol, "limit": chunk, "startTime": start_time}
            try:
                response = self._make_request(FUNDING_URL, params=params)
            except requests.exceptions.RequestException:
                logger.error("Failed to fetch funding-rate history")
                break
            if not isinstance(response, list) or not response:
                break
            rows.extend(response)
            if len(response) < chunk:
                break
            start_time = int(response[-1]["fundingTime"]) + 1

        frame = funding_rows_to_frame(rows)
        if not frame.empty:
            logger.info(
                f"Fetched {len(frame)} daily funding rows "
                f"up to {frame['date'].iloc[-1]}"
            )
        return frame
