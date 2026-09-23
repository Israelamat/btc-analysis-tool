import sys

import pandas as pd

from src.analytics.indicators import calculate_indicator_series
from src.analytics.scoring import BTCAcumulationScorer
from src.fetchers.btc_binance import BTCFetcher
from src.fetchers.fear_greed import FearGreedFetcher
from src.fetchers.fred_m2 import FREDFetcher
from src.fetchers.google_trends import GoogleTrendsFetcher
from src.fetchers.stock_indices import StockIndicesFetcher
from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

TARGET = "all"


def backfill_btc(db: DatabaseManager) -> None:
    """Fetch the full BTC daily history and store it in SQLite."""
    df = BTCFetcher().get_full_history()
    if df.empty:
        logger.warning("No BTC data to backfill")
        return
    written = db.upsert_btc_klines(df)
    logger.info(f"Backfilled {written} BTC daily candles")


def backfill_fear_greed(db: DatabaseManager) -> None:
    """Fetch the Fear & Greed history and store it in SQLite."""
    rows = FearGreedFetcher().get_history(limit=365)
    if not rows:
        logger.warning("No Fear & Greed data to backfill")
        return
    written = db.upsert_fear_greed(rows)
    logger.info(f"Backfilled {written} Fear & Greed records")


def backfill_fred(db: DatabaseManager, series_id: str = "M2SL") -> None:
    """Fetch a FRED series history and store it in SQLite."""
    rows = FREDFetcher().get_history(series_id=series_id)
    if not rows:
        logger.warning(f"No FRED data to backfill for [{series_id}]")
        return
    written = db.upsert_fred(series_id, rows)
    logger.info(f"Backfilled {written} FRED observations for [{series_id}]")


def backfill_google_trends(db: DatabaseManager, keyword: str = "bitcoin") -> None:
    """Fetch the Google Trends interest history for a keyword."""
    rows = GoogleTrendsFetcher().get_history(keyword=keyword)
    if not rows:
        logger.warning(f"No Google Trends data to backfill for [{keyword}]")
        return
    written = db.upsert_google_trends(keyword, rows)
    logger.info(f"Backfilled {written} Google Trends records for [{keyword}]")


def backfill_stocks(db: DatabaseManager) -> None:
    """Fetch SP500 / NASDAQ / DXY daily history and store it in SQLite."""
    df = StockIndicesFetcher().get_history(range_period="1y")
    if df.empty:
        logger.warning("No stock index history to backfill")
        return
    written = db.upsert_stock_history(df)
    logger.info(f"Backfilled {written} stock index daily rows (incl. DXY)")


def backfill_indicators(db: DatabaseManager) -> None:
    """Compute EMA-200 / RSI-14 series from stored BTC klines."""
    klines = db.load_btc_klines()
    if klines.empty:
        logger.warning("btc_klines is empty; run btc backfill first")
        return
    indicators = calculate_indicator_series(klines)
    written = db.upsert_btc_indicators(indicators)
    logger.info(f"Backfilled {written} indicator rows (EMA-200, RSI-14, MACD)")


def _asof(frame: pd.DataFrame, column: str, dates: pd.DatetimeIndex) -> pd.Series:
    """Latest value of a column as of each date (forward-filled)."""
    src = frame.dropna(subset=[column]).set_index("date")[column].sort_index()
    return src.reindex(dates, method="ffill")


def backfill_scores(db: DatabaseManager) -> None:
    """Backfill daily accumulation scores from the stored history.

    Each date needs real BTC indicators and Fear & Greed data; DXY and
    Google Trends fall back to neutral when unavailable.
    """
    indicators = db.load_btc_indicators()
    klines = db.load_btc_klines()
    fear_greed = db.load_fear_greed()
    fred = db.load_fred_series("M2SL")
    stocks = db.load_stock_history()
    trends = db.load_google_trends()

    if indicators.empty or klines.empty or fear_greed.empty:
        logger.warning("Not enough history to backfill scores; run source backfills first")
        return

    for frame in (indicators, klines, fear_greed, fred, stocks, trends):
        if not frame.empty:
            frame["date"] = pd.to_datetime(frame["date"])

    dates = pd.DatetimeIndex(indicators["date"])

    close = _asof(klines, "close", dates)
    sp500 = _asof(stocks, "sp500", dates)
    nasdaq = _asof(stocks, "nasdaq", dates)

    fear_greed_val = _asof(fear_greed, "value", dates)
    google_trends_val = _asof(trends, "value", dates).fillna(50.0)

    m2_series = fred.dropna(subset=["value"]).set_index("date")["value"].sort_index()
    latest = m2_series.reindex(dates, method="ffill")
    base = m2_series.reindex(dates - pd.Timedelta(days=365), method="ffill")
    m2_yoy = pd.Series((latest.to_numpy() / base.to_numpy() - 1) * 100, index=dates)

    dxy_series = stocks.dropna(subset=["dxy"]).set_index("date")["dxy"].sort_index()
    dxy_current = dxy_series.reindex(dates, method="ffill")
    dxy_reference = dxy_series.shift(5).reindex(dates, method="ffill")
    change_pct = (dxy_current / dxy_reference - 1) * 100
    dxy_trend = pd.Series("neutral", index=dates)
    dxy_trend[change_pct > 0.5] = "bullish"
    dxy_trend[change_pct < -0.5] = "bearish"

    frame = pd.DataFrame(
        {
            "date": dates,
            "btc_price": close,
            "ema_200": pd.Series(indicators["ema_200"].array, index=dates),
            "rsi_14": pd.Series(indicators["rsi_14"].array, index=dates),
            "macd_hist": pd.Series(indicators["macd_hist"].array, index=dates),
            "fear_greed": fear_greed_val,
            "m2_yoy": m2_yoy,
            "sp500": sp500,
            "nasdaq": nasdaq,
            "google_trends": google_trends_val,
            "dxy": dxy_trend,
        }
    )
    frame = frame.dropna(subset=["ema_200", "rsi_14", "fear_greed", "m2_yoy"])

    scorer = BTCAcumulationScorer()
    saved = 0
    for _, row in frame.iterrows():
        result = scorer.calculate(
            current_price=row["btc_price"],
            ema_200=row["ema_200"],
            rsi=row["rsi_14"],
            fear_greed=row["fear_greed"],
            m2_yoy=row["m2_yoy"],
            dxy_status=row["dxy"],
            macd_hist=row["macd_hist"],
            google_trends=row["google_trends"],
        )
        db.save_daily_metrics(
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "btc_price": float(row["btc_price"]),
                "ema_200": float(row["ema_200"]),
                "rsi_14": float(row["rsi_14"]),
                "fear_greed": int(row["fear_greed"]),
                "m2_yoy": round(float(row["m2_yoy"]), 2),
                "sp500": None if pd.isna(row["sp500"]) else float(row["sp500"]),
                "nasdaq": None if pd.isna(row["nasdaq"]) else float(row["nasdaq"]),
                "dxy": row["dxy"],
                "macd_hist": round(float(row["macd_hist"]), 4),
                "google_trends": round(float(row["google_trends"]), 2),
                "total_score": result["score"],
            }
        )
        saved += 1

    logger.info(f"Backfilled {saved} accumulation scores")


def run_backfill(target: str = TARGET) -> None:
    """Run the backfill for the selected target.

    Target can be: "all" | "btc" | "fear_greed" | "fred_m2" |
    "google_trends" | "stock_indices" | "indicators" | "scores"
    """
    db = DatabaseManager()
    target = target.lower()

    if target in ("all", "btc"):
        backfill_btc(db)

    if target in ("all", "fear_greed"):
        backfill_fear_greed(db)

    if target in ("all", "fred_m2"):
        backfill_fred(db)

    if target in ("all", "google_trends"):
        backfill_google_trends(db)

    if target in ("all", "stock_indices"):
        backfill_stocks(db)

    if target in ("all", "indicators"):
        backfill_indicators(db)

    if target in ("all", "scores"):
        backfill_scores(db)

    for table, count in db.table_counts().items():
        logger.info(f"table_rows[{table}]={count}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else TARGET
    run_backfill(target)