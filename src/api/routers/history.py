from fastapi import APIRouter
from src.api import queries
from src.api.params import (
    DATE_PARAM,
    END_PARAM,
    LIMIT_PARAM,
    START_PARAM,
    parse_range,
)
from src.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter(tags=["history"])


def _rows(
    source: str,
    limit: int,
    date: str | None,
    start: str | None,
    end: str | None,
) -> dict:
    day, first, last = parse_range(date, start, end)
    return queries.table_series(
        source, limit=limit, date=day, start=first, end=last
    )


@router.get(
    "/score/history",
    summary="Stored daily scores (metrics_history)"
)
def score_history(
    limit: int = LIMIT_PARAM,
    date: str | None = DATE_PARAM,
    start: str | None = START_PARAM,
    end: str | None = END_PARAM,
) -> dict:
    return _rows("scores", limit, date, start, end)


@router.get(
    "/klines",
    summary="BTC/USDT daily candles (btc_klines)"
)
def klines(
    limit: int = LIMIT_PARAM,
    date: str | None = DATE_PARAM,
    start: str | None = START_PARAM,
    end: str | None = END_PARAM,
) -> dict:
    return _rows("klines", limit, date, start, end)


@router.get(
    "/indicators",
    summary="Computed indicators (btc_indicators)"
)
def indicators(
    limit: int = LIMIT_PARAM,
    date: str | None = DATE_PARAM,
    start: str | None = START_PARAM,
    end: str | None = END_PARAM,
) -> dict:
    return _rows("indicators", limit, date, start, end)


@router.get(
    "/fear-greed",
    summary="Fear & Greed index (fear_greed_history)"
)
def fear_greed(
    limit: int = LIMIT_PARAM,
    date: str | None = DATE_PARAM,
    start: str | None = START_PARAM,
    end: str | None = END_PARAM,
) -> dict:
    return _rows("fear-greed", limit, date, start, end)


@router.get(
    "/fred",
    summary="M2 money supply (fred_series)"
)
def fred(
    limit: int = LIMIT_PARAM,
    date: str | None = DATE_PARAM,
    start: str | None = START_PARAM,
    end: str | None = END_PARAM,
) -> dict:
    return _rows("fred", limit, date, start, end)


@router.get(
    "/stocks",
    summary="Equity and dollar data (stock_history)"
)
def stocks(
    limit: int = LIMIT_PARAM,
    date: str | None = DATE_PARAM,
    start: str | None = START_PARAM,
    end: str | None = END_PARAM,
) -> dict:
    return _rows("stocks", limit, date, start, end)


@router.get(
    "/google-trends",
    summary="Search interest (google_trends)"
)
def google_trends(
    limit: int = LIMIT_PARAM,
    date: str | None = DATE_PARAM,
    start: str | None = START_PARAM,
    end: str | None = END_PARAM,
) -> dict:
    return _rows("google-trends", limit, date, start, end)
