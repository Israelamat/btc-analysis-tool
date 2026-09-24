"""Live pipeline: fetch the APIs, run the light analytics and show buy actions.

All the pipeline logic lives here, next to the fetchers, so ``main.py`` stays
a thin entry point:

    fetch APIs  ->  compute indicators + score  ->  present possible buys

Reuses the stored full history for stable indicator values when available and
saves today's metrics so the backtest keeps working.
"""

import json
from datetime import datetime

import pandas as pd

from src.analytics.backtest import _load_klines, forward_return
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

# Buy action per score zone (share of the planned monthly investment to deploy).
ZONE_ACTION = {
    "High accumulation zone": ("COMPRA FUERTE", 1.0),
    "Moderate accumulation zone": ("COMPRA NORMAL (DCA)", 0.5),
    "Neutral zone": ("COMPRA LIGERA", 0.25),
    "Selling zone": ("NO COMPRAR (protege capital)", 0.0),
}

MONTHLY_EXAMPLE = 1000


def _zone_history_stats(
    db: DatabaseManager, zone: str, horizon: int = 90
) -> dict | None:
    """Historical n / mean return / win rate for the current zone (if stored)."""
    metrics = db.load_metrics_history()
    if metrics.empty or "zone" not in metrics.columns:
        return None
    metrics["date"] = pd.to_datetime(metrics["date"])
    sub = metrics[metrics["zone"] == zone]
    if sub.empty:
        return None

    klines = _load_klines(db)
    if klines.empty:
        return {"n": int(len(sub))}

    returns = forward_return(klines, pd.DatetimeIndex(sub["date"]), horizon)
    values = returns.dropna()
    if values.empty:
        return None

    return {
        "n": int(len(sub)),
        "mean": float(values.mean()),
        "win": float((values > 0).mean()) * 100,
    }


def _latest_stored_trends(
    db: DatabaseManager, max_age_days: int = 30
) -> float | None:
    """Latest stored Google Trends value if it is fresh enough."""
    trends = db.load_google_trends()
    if trends.empty or "date" not in trends.columns or "value" not in trends.columns:
        return None
    trends["date"] = pd.to_datetime(trends["date"])
    last = trends.sort_values("date").iloc[-1]
    age_days = (datetime.now() - last["date"].to_pydatetime()).days
    if 0 <= age_days <= max_age_days:
        return float(last["value"])
    return None


def _print_report(db: DatabaseManager, record: dict, score_result: dict) -> None:
    zone = score_result["zone"]
    action, ratio = ZONE_ACTION[zone]

    top = sorted(
        score_result["components"].items(), key=lambda item: -item[1]
    )[:3]

    print("\n=== Resumen del Análisis ===")
    print(f"[+] Precio BTC: ${record['btc_price']:,.2f}")
    print(f"[+] Score de Acumulación: {score_result['score']}/100")
    print(f"[+] Clasificación: {zone}")
    print(
        "[+] Señales más fuertes: "
        + ", ".join(f"{key}={value:.0f}" for key, value in top)
    )
    print(
        f"[+] S&P 500: {record['sp500']} | NASDAQ: {record['nasdaq']} | "
        f"EMA-200: ${record['ema_200']:,.2f}"
    )

    print("\n=== Posibles Compras ===")
    amount = MONTHLY_EXAMPLE * ratio
    print(f"[+] Acción recomendada: {action}")
    print(
        f"[+] Invertir ahora {ratio:.0%} del monto mensual "
        f"(~${amount:,.0f} de ${MONTHLY_EXAMPLE:,.0f})"
    )
    stats = _zone_history_stats(db, zone)
    if stats and "mean" in stats:
        print(
            f"[+] En esta zona, históricamente: retorno medio 90d "
            f"{stats['mean']:+.1f}% | acierto {stats['win']:.1f}% | "
            f"({stats['n']} fechas)"
        )
    print()


def run_pipeline() -> None:
    """Fetch everything, score the market and present the buy action."""
    logger.info("Init pipeline...")

    db = DatabaseManager()

    btc_df = BTCFetcher().get_daily_klines(limit=250)
    if btc_df.empty:
        logger.error("No BTC data available, aborting pipeline")
        return

    fear_greed_val = FearGreedFetcher().get_latest_score()
    m2_growth = FREDFetcher().get_m2_yoy_growth()
    stocks_data = StockIndicesFetcher().get_major_indices()
    google_trends_val = GoogleTrendsFetcher().get_latest_value()
    if google_trends_val == 50.0:
        stored = _latest_stored_trends(db)
        if stored is not None:
            google_trends_val = stored
            logger.info(
                f"Using stored Google Trends value {stored:.0f} "
                f"(fetch fell back to neutral)"
            )

    logger.info("Calculating technical indicators...")
    tech_data = calculate_technical_indicators(btc_df)

    # Prefer indicators from the full stored history (backfill) so today's
    # score is consistent with the historical series.
    stored_indicators = db.load_btc_indicators()
    if not stored_indicators.empty:
        last_row = stored_indicators.iloc[-1]
        stored_date = pd.to_datetime(last_row["date"]).date()
        if str(stored_date) == str(tech_data.get("latest_date")):
            tech_data["ema_200"] = float(last_row["ema_200"])
            tech_data["rsi"] = float(last_row["rsi_14"])
            tech_data["macd_hist"] = float(last_row["macd_hist"])
            logger.info("Using indicators from full stored history")

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
        "zone": score_result["zone"],
        "components": json.dumps(score_result["components"], ensure_ascii=False),
    }

    logger.info("Saving results to database...")
    db.save_daily_metrics(today_record)

    _print_report(db, today_record, score_result)