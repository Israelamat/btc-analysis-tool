from fastapi import APIRouter
from src.api import queries
from src.api.params import DATE_PARAM, LIMIT_PARAM, parse_date
from src.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter(tags=["history"])


def _rows(source: str, limit: int, date: str | None) -> dict:
    return queries.table_series(
        source, limit=limit, date=parse_date(date, "date") if date else None
    )


@router.get(
    "/score/history",
    summary="Stored daily scores (metrics_history)"
)
def score_history(limit: int = LIMIT_PARAM, date: str | None = DATE_PARAM) -> dict:
    return _rows("scores", limit, date)


@router.get(
    "/klines",
    summary="BTC/USDT daily candles (btc_klines)"
)
def klines(limit: int = LIMIT_PARAM, date: str | None = DATE_PARAM) -> dict:
    return _rows("klines", limit, date)


@router.get(
    "/indicators",
    summary="Computed indicators (btc_indicators)"
)
def indicators(limit: int = LIMIT_PARAM, date: str | None = DATE_PARAM) -> dict:
    return _rows("indicators", limit, date)


@router.get(
    "/fear-greed",
    summary="Fear & Greed index (fear_greed_history)"
)
def fear_greed(limit: int = LIMIT_PARAM, date: str | None = DATE_PARAM) -> dict:
    return _rows("fear-greed", limit, date)


@router.get(
    "/fred",
    summary="M2 money supply (fred_series)"
)
def fred(limit: int = LIMIT_PARAM, date: str | None = DATE_PARAM) -> dict:
    return _rows("fred", limit, date)


@router.get(
    "/stocks",
    summary="Equity and dollar data (stock_history)"
)
def stocks(limit: int = LIMIT_PARAM, date: str | None = DATE_PARAM) -> dict:
    return _rows("stocks", limit, date)


@router.get(
    "/google-trends",
    summary="Search interest (google_trends)"
)
def google_trends(limit: int = LIMIT_PARAM, date: str | None = DATE_PARAM) -> dict:
    return _rows("google-trends", limit, date)
