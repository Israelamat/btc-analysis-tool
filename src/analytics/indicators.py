import numpy as np
import pandas as pd

from src.utils.logger import setup_logger

logger = setup_logger()


def _rsi(series: pd.Series, period: int = 14) -> float:
    """Wilder's Relative Strength Index for the last value of a series."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    last_avg_gain = float(avg_gain.iloc[-1])
    last_avg_loss = float(avg_loss.iloc[-1])

    if last_avg_loss == 0:
        return 100.0
    if last_avg_gain == 0:
        return 0.0

    rs = last_avg_gain / last_avg_loss
    return float(100 - (100 / (1 + rs)))


def calculate_technical_indicators(
    df: pd.DataFrame, ema_period: int = 200, rsi_period: int = 14
) -> dict:
    """Compute the technical indicators used by the scoring model.

    :param df: DataFrame with at least a 'close' column (from BTCFetcher)
    :param ema_period: EMA period used as trend benchmark
    :param rsi_period: RSI period
    :return: dict with latest_price, ema_200 and rsi
    """
    if df is None or df.empty or "close" not in df.columns:
        logger.warning("No data available to compute technical indicators")
        return {"latest_price": 0.0, "ema_200": 0.0, "rsi": 50.0, "macd_hist": 0.0}

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if close.empty:
        logger.warning("Close prices are not valid")
        return {"latest_price": 0.0, "ema_200": 0.0, "rsi": 50.0, "macd_hist": 0.0}

    latest_price = float(close.iloc[-1])
    ema_200 = float(close.ewm(span=ema_period, adjust=False).mean().iloc[-1])

    try:
        rsi = _rsi(close, rsi_period)
        if np.isnan(rsi):
            rsi = 50.0
    except Exception:
        rsi = 50.0
        logger.warning("Failed to compute RSI, using neutral value 50")

    try:
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = float((macd - macd_signal).iloc[-1])
        if np.isnan(macd_hist):
            macd_hist = 0.0
    except Exception:
        macd_hist = 0.0
        logger.warning("Failed to compute MACD histogram, using neutral value 0")

    logger.info(
        f"Indicators: price={latest_price:.2f} "
        f"EMA{ema_period}={ema_200:.2f} RSI{rsi_period}={rsi:.2f} "
        f"MACD_hist={macd_hist:.4f}"
    )
    return {
        "latest_price": latest_price,
        "ema_200": ema_200,
        "rsi": round(rsi, 2),
        "macd_hist": round(macd_hist, 4),
    }


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi_series(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI computed for the whole series."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rsi = 100 - (100 / (1 + avg_gain / avg_loss))
    rsi = rsi.where(avg_loss != 0, 100.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss != 0), 0.0)
    return rsi


def calculate_indicator_series(
    df: pd.DataFrame, ema_period: int = 200, rsi_period: int = 14
) -> pd.DataFrame:
    """Compute EMA-200, RSI-14 and MACD series for every kline.

    :param df: DataFrame with at least a 'close' column (from BTCFetcher)
    :param ema_period: EMA period used as trend benchmark
    :param rsi_period: RSI period
    :return: DataFrame with date, ema_200, rsi_14, macd, macd_signal, macd_hist
    """
    columns = ["date", "ema_200", "rsi_14", "macd", "macd_signal", "macd_hist"]
    if df is None or df.empty or "close" not in df.columns:
        logger.warning("No data available to compute indicator series")
        return pd.DataFrame(columns=columns)

    close = pd.to_numeric(df["close"], errors="coerce")
    out = pd.DataFrame({"date": df["date"]})

    out["ema_200"] = _ema(close, ema_period)
    out["rsi_14"] = _rsi_series(close, rsi_period)

    macd = _ema(close, 12) - _ema(close, 26)
    out["macd"] = macd
    out["macd_signal"] = _ema(macd, 9)
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    logger.info(f"Computed {len(out)} rows of indicator series")
    return out[columns]