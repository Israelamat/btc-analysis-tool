import json
from datetime import datetime

import pandas as pd

from src.analytics.backtest import _load_klines, forward_return
from src.analytics.indicators import (
    calculate_indicator_series,
    calculate_technical_indicators,
)
from src.analytics.scoring import (
    BTCAcumulationScorer,
    allocation_pct,
    allocation_signal,
)
from src.fetchers.btc_binance import BTCFetcher
from src.fetchers.fear_greed import FearGreedFetcher
from src.fetchers.fred_m2 import FREDFetcher
from src.fetchers.google_trends import GoogleTrendsFetcher
from src.fetchers.stock_indices import StockIndicesFetcher
from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()


def _optional_float(value) -> float | None:
    """Coerce a value to float, mapping None/NaN/empty to None."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(result) else result

# Coarse action label per zone. The continuous buy/sell percentage comes from
# scoring.allocation_pct (0% at score 30, 100% at score 70).
ZONE_ACTION = {
    "High accumulation zone": ("COMPRA FUERTE", 1.0),
    "Moderate accumulation zone": ("COMPRA NORMAL (DCA)", 0.5),
    "Neutral zone": ("COMPRA LIGERA", 0.25),
    "Selling zone": ("NO COMPRAR (protege capital)", 0.0),
}

MONTHLY_EXAMPLE = 1000


def zone_history_stats(
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


def _previous_stored_score(db: DatabaseManager, date_value) -> float | None:
    """Latest stored score strictly before ``date_value`` (the prior position)."""
    history = db.load_latest_metrics(limit=30)
    if history.empty or "total_score" not in history.columns:
        return None
    history["date"] = pd.to_datetime(history["date"], errors="coerce")
    target = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(target):
        return None
    prior = history[history["date"] < target]
    if prior.empty:
        return None
    return _optional_float(prior.sort_values("date").iloc[-1]["total_score"])


def _print_report(db: DatabaseManager, record: dict, score_result: dict) -> None:
    zone = score_result["zone"]
    action, _ = ZONE_ACTION[zone]
    target_pct = allocation_pct(score_result["score"])
    signal = allocation_signal(
        score_result["score"], _previous_stored_score(db, record["date"])
    )

    top = sorted(
        score_result["components"].items(), key=lambda item: -item[1]
    )[:3]

    print("\n=== Resumen del Análisis ===")
    print(f"[+] Precio BTC: ${record['btc_price']:,.2f}")
    print(f"[+] Score de Acumulación: {score_result['score']}/100")
    print(f"[+] Clasificación: {zone}")
    if score_result.get("low_confidence"):
        missing = score_result.get("missing") or []
        print(
            f"[!] Confianza baja: solo {score_result['coverage']:.0%} de las "
            f"señales disponibles"
            + (f" (faltan: {', '.join(missing)})" if missing else "")
        )
    print(
        "[+] Señales más fuertes: "
        + ", ".join(f"{key}={value:.0f}" for key, value in top)
    )
    print(
        f"[+] S&P 500: {record['sp500']} | NASDAQ: {record['nasdaq']} | "
        f"EMA-200: ${record['ema_200']:,.2f}"
    )

    print("\n=== Posibles Compras ===")
    print(f"[+] Acción recomendada: {action}")
    if target_pct is None:
        print("[+] Asignación objetivo: sin datos suficientes")
    else:
        amount = MONTHLY_EXAMPLE * target_pct / 100
        print(
            f"[+] Asignación objetivo: {target_pct:.0f}% del capital en BTC "
            f"(~${amount:,.0f} de ${MONTHLY_EXAMPLE:,.0f})"
        )
        if signal["action"] == "BUY":
            print(
                f"[+] Señal: COMPRAR {signal['buy_pct']:.0f}% del capital "
                f"(objetivo {signal['target_pct']:.0f}% vs "
                f"{signal['previous_target_pct'] or 0:.0f}% previo)"
            )
        elif signal["action"] == "SELL":
            print(
                f"[+] Señal: VENDER {signal['sell_pct']:.0f}% del capital "
                f"(objetivo {signal['target_pct']:.0f}% vs "
                f"{signal['previous_target_pct'] or 0:.0f}% previo)"
            )
        else:
            print(
                f"[+] Señal: MANTENER (objetivo {signal['target_pct']:.0f}%, "
                "sin cambio frente al día previo)"
            )
    stats = zone_history_stats(db, zone)
    if stats and "mean" in stats:
        print(
            f"[+] En esta zona, históricamente: retorno medio 90d "
            f"{stats['mean']:+.1f}% | acierto {stats['win']:.1f}% | "
            f"({stats['n']} fechas)"
        )
    print()


def collect_market_snapshot(db: DatabaseManager) -> dict | None:
    """Fetch every live source, score the market and return the snapshot.

    This is the single place where the console report and the REST API get
    their numbers from, so both always agree.

    :param db: database used for the stored indicator / Google Trends fallbacks
        and where the fetched candles are persisted
    :return: dict with 'record' (DB-ready, components serialized as JSON),
        'components' (per-signal scores as floats), 'score_result' and
        'sources' (which fallbacks were used), or None when BTC data is
        unavailable
    """
    logger.info("Init pipeline...")

    btc_df = BTCFetcher().get_daily_klines(limit=250)
    if btc_df.empty:
        logger.error("No BTC data available, aborting pipeline")
        return None

    # Persist the candles so btc_klines never lags behind metrics_history:
    # /api/price, the zone price context and the backtest windows all read
    # this table, and today is only stored in metrics_history otherwise.
    saved_candles = db.upsert_btc_klines(btc_df)
    logger.info(f"Stored {saved_candles} BTC candles")

    # Recompute the indicator series (incl. SMA-365, which needs the full
    # history) so a daily run keeps btc_indicators in step with btc_klines.
    indicator_series = calculate_indicator_series(db.load_btc_klines())
    if not indicator_series.empty:
        saved_indicators = db.upsert_btc_indicators(indicator_series)
        logger.info(f"Stored {saved_indicators} indicator rows")

    fear_greed_val = FearGreedFetcher().get_latest_score()
    m2_growth = FREDFetcher().get_m2_yoy_growth()
    stocks_data = StockIndicesFetcher().get_major_indices()
    google_trends_val = GoogleTrendsFetcher().get_latest_value()
    trends_fallback = False
    if google_trends_val is None:
        stored = _latest_stored_trends(db)
        if stored is not None:
            google_trends_val = stored
            trends_fallback = True
            logger.info(
                f"Using stored Google Trends value {stored:.0f} "
                f"(fresh fetch unavailable)"
            )

    logger.info("Calculating technical indicators...")
    tech_data = calculate_technical_indicators(btc_df)

    # On-chain valuation proxies come off the freshly recomputed series (its
    # last row is today, since the current candle was upserted above).
    proxy_mvrv = None
    proxy_nupl = None
    if not indicator_series.empty and "mvrv" in indicator_series.columns:
        proxy_mvrv = _optional_float(indicator_series["mvrv"].iloc[-1])
        proxy_nupl = _optional_float(indicator_series["nupl"].iloc[-1])

    # Prefer indicators from the full stored history (backfill) so today's
    # score is consistent with the historical series.
    stored_indicators = db.load_btc_indicators()
    stored_indicators_used = False
    if not stored_indicators.empty:
        last_row = stored_indicators.iloc[-1]
        stored_date = pd.to_datetime(last_row["date"]).date()
        if str(stored_date) == str(tech_data.get("latest_date")):
            tech_data["ema_200"] = float(last_row["ema_200"])
            tech_data["rsi"] = float(last_row["rsi_14"])
            tech_data["macd_hist"] = float(last_row["macd_hist"])
            stored_indicators_used = True
            logger.info("Using indicators from full stored history")

    logger.info("Calculating score...")
    scorer = BTCAcumulationScorer()
    score_result = scorer.calculate(
        current_price=tech_data["latest_price"],
        ema_200=tech_data["ema_200"],
        rsi=tech_data["rsi"],
        fear_greed=fear_greed_val,
        m2_yoy=m2_growth,
        dxy_status=stocks_data.get("DXY_trend"),
        macd_hist=tech_data["macd_hist"],
        google_trends=google_trends_val,
        proxy_mvrv=proxy_mvrv,
        proxy_nupl=proxy_nupl,
    )

    record = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "btc_price": tech_data["latest_price"],
        "ema_200": tech_data["ema_200"],
        "rsi_14": tech_data["rsi"],
        "fear_greed": fear_greed_val,
        "m2_yoy": m2_growth,
        "sp500": stocks_data.get("SP500"),
        "nasdaq": stocks_data.get("NASDAQ"),
        "dxy": stocks_data.get("DXY_trend"),
        "macd_hist": tech_data["macd_hist"],
        "google_trends": google_trends_val,
        "total_score": score_result["score"],
        "zone": score_result["zone"],
        "components": json.dumps(score_result["components"], ensure_ascii=False),
        "coverage": score_result["coverage"],
    }

    return {
        "record": record,
        "components": score_result["components"],
        "score_result": score_result,
        "latest_candle_date": tech_data.get("latest_date"),
        "sources": {
            "google_trends_fallback": trends_fallback,
            "stored_indicators": stored_indicators_used,
            "sp500": stocks_data.get("SP500") is not None,
            "nasdaq": stocks_data.get("NASDAQ") is not None,
            "m2": m2_growth is not None,
        },
    }


def run_pipeline() -> None:
    """Fetch everything, score the market and present the buy action."""
    db = DatabaseManager()
    snapshot = collect_market_snapshot(db)
    if snapshot is None:
        return

    logger.info("Saving results to database...")
    db.save_daily_metrics(snapshot["record"])

    _print_report(db, snapshot["record"], snapshot["score_result"])