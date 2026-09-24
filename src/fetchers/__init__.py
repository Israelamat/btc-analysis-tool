"""Fetchers: public market and macro data providers."""

from .base import BaseFetcher
from .btc_binance import BTCFetcher
from .fear_greed import FearGreedFetcher
from .fred_m2 import FREDFetcher
from .google_trends import GoogleTrendsFetcher
from .stock_indices import StockIndicesFetcher

__all__ = [
    "BaseFetcher",
    "BTCFetcher",
    "FearGreedFetcher",
    "FREDFetcher",
    "GoogleTrendsFetcher",
    "StockIndicesFetcher",
]