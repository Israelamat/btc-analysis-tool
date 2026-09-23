import pandas as pd
import requests

from src.config import Config
from src.fetchers.base import BaseFetcher
from src.utils.logger import setup_logger

logger = setup_logger()


class FREDFetcher(BaseFetcher):
    """Connector for FRED (Federal Reserve Bank of St. Louis) series."""

    BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
    SERIES_ID = "M2SL"

    def fetch_data(self, series_id: str = SERIES_ID, limit: int = 20000) -> list[dict]:
        """Fetch observations for a FRED series.

        Only observations with a numeric value are returned.

        :param series_id: FRED series id, e.g. M2SL (M2 money stock)
        :param limit: Number of observations to fetch (descending order)
        :return: List of observation dicts
        """
        if not Config.FRED_API_KEY:
            logger.error("FRED_API_KEY is not configured in .env")
            return []

        params = {
            "series_id": series_id,
            "api_key": Config.FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }
        try:
            response = self._make_request(self.BASE_URL, params=params)
        except requests.exceptions.RequestException:
            logger.error(f"Failed to fetch FRED series [{series_id}]")
            return []

        observations = response.get("observations", [])
        return [
            obs
            for obs in observations
            if obs.get("value") not in (None, "") and obs["value"] != "."
        ]

    def get_m2_yoy_growth(self) -> float:
        """Return M2 money supply year-over-year growth in percent.

        Falls back to 0.0 if the data cannot be fetched or is insufficient.
        """
        observations = self.fetch_data()
        if len(observations) < 2:
            logger.warning("Not enough M2 observations to compute YoY growth")
            return 0.0

        df = pd.DataFrame(observations)
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"]).sort_values("date").drop_duplicates("date")

        if len(df) < 2:
            logger.warning("Not enough valid M2 observations")
            return 0.0

        latest = df.iloc[-1]
        target_date = latest["date"] - pd.DateOffset(years=1)
        past = df[df["date"] <= target_date]

        if past.empty:
            logger.warning("No M2 observation found one year back")
            return 0.0

        year_ago_value = past.iloc[-1]["value"]
        if year_ago_value <= 0:
            logger.warning("Invalid M2 base value for YoY computation")
            return 0.0

        yoy = (latest["value"] / year_ago_value - 1) * 100
        logger.info(f"M2 YoY growth: {yoy:.2f}% (as of {latest['date'].date()})")
        return round(float(yoy), 2)

    def get_history(
        self, series_id: str = SERIES_ID, limit: int = 20000
    ) -> list[dict]:
        """Return the observations for a FRED series as date/value dicts.

        :param series_id: FRED series id, e.g. M2SL (M2 money stock)
        :param limit: Number of observations to fetch (descending order)
        :return: List of dicts with date (YYYY-MM-DD) and value (float)
        """
        observations = self.fetch_data(series_id=series_id, limit=limit)
        rows = [
            {"date": obs["date"], "value": float(obs["value"])}
            for obs in observations
        ]
        logger.info(f"Fetched {len(rows)} observations for FRED [{series_id}]")
        return rows