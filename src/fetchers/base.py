from abc import ABC, abstractmethod
import requests
from src.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}


class BaseFetcher(ABC):
    """Abstract class for fetching data from an API."""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def _make_request(self, url: str, params: dict = None, headers: dict = None) -> dict:
        """Do request to API."""
        try:
            merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
            response = requests.get(
                url, params=params, headers=merged_headers, timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching [{url}]: {e}")
            raise

    @abstractmethod
    def fetch_data(self):
        """Abstract method necessary to be implemented by subclasses."""
        pass