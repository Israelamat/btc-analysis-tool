from fastapi import APIRouter, Query

from src.api import queries
from src.api.schemas import DashboardResponse
from src.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter(tags=["dashboard"])

@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Everything the dashboard needs in one call",
)
def dashboard(
    days: int = Query(
        90, ge=7, le=1825
    ),
) -> dict:
    return queries.dashboard(days=days)
