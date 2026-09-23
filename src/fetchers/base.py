import time
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

DEFAULT_MAX_RETRIES = 3
MAX_BACKOFF_SECONDS = 6


class BaseFetcher(ABC):
    """Abstract class for fetching data from an API."""

    def __init__(self, timeout: int = 10, max_retries: int = DEFAULT_MAX_RETRIES):
        self.timeout = timeout
        self.max_retries = max_retries

    def _make_request(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> dict | list:
        """Do request to API with retries and exponential backoff.

        :raises requests.exceptions.RequestException: when every attempt fails
        """
        merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
        last_error: requests.exceptions.RequestException | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.get(
                    url, params=params, headers=merged_headers, timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(
                    f"Error fetching [{url}] "
                    f"(attempt {attempt}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, MAX_BACKOFF_SECONDS))

        logger.error(f"Error fetching [{url}]: {last_error}")
        raise last_error

    @abstractmethod
    def fetch_data(self):
        """Abstract method necessary to be implemented by subclasses."""
        pass