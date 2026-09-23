import argparse
from datetime import datetime

from src.analytics.indicators import calculate_technical_indicators
from src.analytics.scoring import BTCAcumulationScorer
from src.fetchers.btc_binance import BTCFetcher
from src.fetchers.fear_greed import FearGreedFetcher
from src.fetchers.fred_m2 import FREDFetcher
from src.fetchers.google_trends import GoogleTrendsFetcher
from src.fetchers.stock_indices import StockIndicesFetcher
from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()


def run_pipeline():
    logger.info("Init pipeline...")

    btc_df = BTCFetcher().get_daily_klines(limit=250)
    if btc_df.empty:
        logger.error("No BTC data available, aborting pipeline")
        return

    fear_greed_val = FearGreedFetcher().get_latest_score()
    m2_growth = FREDFetcher().get_m2_yoy_growth()
    stocks_data = StockIndicesFetcher().get_major_indices()
    google_trends_val = GoogleTrendsFetcher().get_latest_value()

    logger.info("Calculating technical indicators...")
    tech_data = calculate_technical_indicators(btc_df)

    logger.info("Calculating score...")
    scorer = BTCAcumulationScorer()
    score_result = scorer.calculate(
        current_price=tech_data["latest_price"],
        ema_200=tech_data["ema_200"],
        rsi=tech_data["rsi"],
        fear_greed=fear_greed_val,
        m2_yoy=m2_growth,
        dxy_status=stocks_data.get("DXY_trend", "neutral"),
        macd_hist=tech_data["macd_hist"],
        google_trends=google_trends_val,
    )

    today_record = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "btc_price": tech_data["latest_price"],
        "ema_200": tech_data["ema_200"],
        "rsi_14": tech_data["rsi"],
        "fear_greed": fear_greed_val,
        "m2_yoy": m2_growth,
        "sp500": stocks_data.get("SP500"),
        "nasdaq": stocks_data.get("NASDAQ"),
        "dxy": stocks_data.get("DXY_trend", "neutral"),
        "macd_hist": tech_data["macd_hist"],
        "google_trends": google_trends_val,
        "total_score": score_result["score"],
    }

    logger.info("Saving results to database...")
    db = DatabaseManager()
    db.save_daily_metrics(today_record)

    logger.info("=== Resumen del Análisis ===")
    print(f"\n[+] Precio BTC: ${today_record['btc_price']:,.2f}")
    print(f"[+] Score de Acumulación BTC: {score_result['score']}/100")
    print(f"[+] Clasificación: {score_result['zone']}")
    print(
        f"[+] S&P 500: {today_record['sp500']} | NASDAQ: {today_record['nasdaq']}\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bitcoin & Macro Accumulation Analysis Tool"
    )
    parser.add_argument(
        "--run", action="store_true", help="Init pipeline and run analysis"
    )
    args = parser.parse_args()

    if not args.run:
        parser.print_help()
    else:
        run_pipeline()