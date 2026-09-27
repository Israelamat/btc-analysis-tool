from fastapi import APIRouter
from src.api import queries
from src.api.schemas import ModelConfigResponse
from src.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter(tags=["meta"])


@router.get(
    "/config",
    response_model=ModelConfigResponse,
    summary="Weights, zone thresholds and buy actions"
)
def config() -> dict:
    return queries.model_config()
