from datetime import datetime

import pandas as pd
from pytrends.request import TrendReq

from src.config import Config
from src.fetchers.base import BaseFetcher
from src.utils.logger import setup_logger

logger = setup_logger()


class GoogleTrendsFetcher(BaseFetcher):
    """Connector for Google Trends search interest.

    Uses the unofficial pytrends client to fetch the "interest over time"
    metric (0-100 scale) for a keyword, e.g. how often "bitcoin" is searched.
    """

    def __init__(self, hl: str = "en-US", tz: int = 0, timeout: int = 30):
        super().__init__(timeout=timeout)
        self.hl = hl
        self.tz = tz
        self._client: TrendReq | None = None
        self._cache: dict[tuple[str, str], pd.DataFrame] = {}

    def _get_client(self) -> TrendReq:
        """Lazily build the pytrends client."""
        if self._client is None:
            self._client = TrendReq(hl=self.hl, tz=self.tz, timeout=self.timeout)
        return self._client

    def fetch_data(
        self, keyword: str = "bitcoin", timeframe: str = "today 5-y"
    ) -> pd.DataFrame:
        """Fetch the interest-over-time data for a keyword.

        :param keyword: Search term, e.g. bitcoin
        :param timeframe: Google Trends window, e.g. "today 5-y"
        :return: DataFrame with columns date and value (0-100 scale)
        """
        cache_key = (keyword, timeframe)
        if cache_key in self._cache:
            return self._cache[cache_key].copy()

        try:
            client = self._get_client()
            client.build_payload([keyword], timeframe=timeframe)
            df = client.interest_over_time()
        except Exception as e:
            logger.error(f"Failed to fetch Google Trends for [{keyword}]: {e}")
            return pd.DataFrame(columns=["date", "value"])

        if df.empty or keyword not in df.columns:
            logger.warning(f"No Google Trends data for [{keyword}]")
            return pd.DataFrame(columns=["date", "value"])

        df = df[[keyword]].copy()
        df.columns = ["value"]
        df.index.name = "date"
        df = df[df["value"].notna()]
        df = df.reset_index()
        self._cache[cache_key] = df.copy()
        return df

    def get_history(
        self,
        keyword: str = "bitcoin",
        years: int | None = None,
        start_date: str | None = None,
    ) -> list[dict]:
        """Return the Google Trends interest history for a keyword.

        :param keyword: Search term, e.g. bitcoin
        :param years: Lookback window in years (Google caps it at 5).
            Ignored when ``start_date`` is provided.
        :param start_date: First day to include (YYYY-MM-DD); defaults to
            ``Config.START_DATE``.
        :return: List of dicts with date and value (0-100 scale)
        """
        if start_date is None:
            start_date = Config.START_DATE

        if years is not None:
            timeframe = f"today {years}-y"
        else:
            timeframe = f"{start_date} {datetime.now().strftime('%Y-%m-%d')}"

        frame = self.fetch_data(keyword=keyword, timeframe=timeframe)
        if frame.empty:
            return []

        rows = [
            {"date": row.date.strftime("%Y-%m-%d"), "value": int(row.value)}
            for row in frame.itertuples()
        ]
        rows = [r for r in rows if r["date"] >= start_date]
        logger.info(f"Fetched {len(rows)} Google Trends records for [{keyword}]")
        return rows

    def get_latest_value(self, keyword: str = "bitcoin") -> float:
        """Return the latest Google Trends interest value (0-100).

        Falls back to 50 (neutral) when no data is available.
        """
        rows = self.get_history(keyword=keyword, years=1)
        if not rows:
            logger.warning("Using neutral Google Trends value 50")
            return 50.0
        logger.info(
            f"Google Trends [{keyword}]: {rows[-1]['value']} "
            f"(as of {rows[-1]['date']})"
        )
        return float(rows[-1]["value"])