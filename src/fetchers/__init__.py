import sys

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

TARGET = "all"


def run_fetcher_test(target: str = TARGET) -> None:
    """Test the fetchers selected by target.

    Target can be: "all" | "btc" | "fear_greed" | "fred_m2" |
    "google_trends" | "stock_indices"
    """
    target = target.lower()

    if target in ("all", "btc"):
        btc_df = BTCFetcher().get_daily_klines(limit=5)
        print(f"[+] BTC: {len(btc_df)} candles")
        if not btc_df.empty:
            last = btc_df.iloc[-1]
            print(f"    Last={last['date']} close=${last['close']:,.2f}")
        print()

    if target in ("all", "fear_greed"):
        score = FearGreedFetcher().get_latest_score()
        print(f"[+] Fear & Greed: {score}")
        print()

    if target in ("all", "fred_m2"):
        yoy = FREDFetcher().get_m2_yoy_growth()
        print(f"[+] M2 YoY: {yoy}%")
        print()

    if target in ("all", "stock_indices"):
        stocks = StockIndicesFetcher().get_major_indices()
        print(f"[+] Stocks: {stocks}")
        print()

    if target in ("all", "google_trends"):
        trends = GoogleTrendsFetcher().get_history(years=1)
        print(f"[+] Google Trends: {len(trends)} records")
        if trends:
            print(f"    Last={trends[-1]}")
        print()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else TARGET
    run_fetcher_test(target)