from datetime import date as date_cls
from fastapi import HTTPException, Query

MAX_LIMIT = 20

LIMIT_PARAM = Query(
    MAX_LIMIT,
    ge=1,
    le=MAX_LIMIT,
    description=f"Max rows returned, most recent ones (max. {MAX_LIMIT})",
)
DATE_PARAM = Query(None, description="Return only this date, YYYY-MM-DD")


def parse_date(value: str, field: str) -> str:
    """Validate a ``YYYY-MM-DD`` query parameter.

    :raises HTTPException: 422 when the value is not an ISO calendar date
    """
    try:
        return date_cls.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"{field} must be YYYY-MM-DD, got '{value}'"
        )
