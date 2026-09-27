from typing import Any
from fastapi import APIRouter, HTTPException
from src.api import queries
from src.api.schemas import ScoreSnapshot
from src.fetchers.pipeline import collect_market_snapshot
from src.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(tags=["report"])


@router.post(
    "/refresh",
    response_model=ScoreSnapshot,
    summary="Runs the pipeline live and stores the result"
)
def refresh() -> Any:
    db = queries.get_db()
    snapshot = collect_market_snapshot(db)
    if snapshot is None:
        raise HTTPException(
            status_code=503, detail="No BTC data available; the pipeline aborted"
        )

    record = snapshot["record"]
    db.save_daily_metrics(record)
    queries.clear_cache()
    logger.info(f"Refresh served live report for {record['date']}")

    return {
        **queries.report_from_record(record, snapshot["components"]),
        "source": "live",
        "latest_candle_date": snapshot.get("latest_candle_date"),
        "fallbacks": snapshot.get("sources"),
    }
