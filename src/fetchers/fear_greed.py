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