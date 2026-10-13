from fastapi import APIRouter, Query

from src.api import queries
from src.api.schemas import ValuationResponse
from src.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter(tags=["valuation"])


@router.get(
    "/valuation",
    response_model=ValuationResponse,
    summary="Price / SMA-365 ratio (homemade MVRV) and its 0-100 score",
)
def valuation(
    days: int = Query(365, ge=1, le=1825),
) -> dict:
    return queries.valuation_ratio(days=days)
