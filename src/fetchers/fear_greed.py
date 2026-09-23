from datetime import datetime

from src.fetchers.base import BaseFetcher
from src.utils.logger import setup_logger

logger = setup_logger()


class FearGreedFetcher(BaseFetcher):
    """Connector for the Fear & Greed Index API"""

    BASE_URL = "https://api.alternative.me/fng/"

    def fetch_data(self, limit: int = 1) -> list[dict]:
        """Get Fear & Greed Index data.

        :param limit: Number of items to fetch 
        return list[dict]: List of Fear & Greed Index data
        """
        params = {"limit": limit, "format": "json"}
        response = self._make_request(self.BASE_URL, params=params)

        if "data" in response and len(response["data"]) > 0:
            return response["data"]

        logger.warning("Empty response from of  Fear & Greed API")
        return []

    def get_latest_score(self) -> int:
        """Return the latest Fear & Greed Index value."""
        data = self.fetch_data(limit=1)
        if data:
            val = int(data[0]["value"])
            classification = data[0]["value_classification"]
            logger.info(
                f"Fear & Greed Index: {val} ({classification})"
            )
            return val

        logger.warning(
            "Using default value for Fear & Greed Index (50) since no data was found"
        )
        return 50

    def get_history(self, limit: int = 365) -> list[dict]:
        """Return the Fear & Greed history as date/value/classification dicts.

        :param limit: Number of historical items to fetch
        :return: List of dicts with date (YYYY-MM-DD), value (int) and
            classification (str)
        """
        data = self.fetch_data(limit=limit)
        rows = []
        for item in data:
            timestamp = item.get("timestamp")
            if not timestamp:
                continue
            rows.append(
                {
                    "date": datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d"),
                    "value": int(item["value"]),
                    "classification": item.get("value_classification"),
                }
            )
        logger.info(f"Fetched {len(rows)} Fear & Greed history records")
        return rows