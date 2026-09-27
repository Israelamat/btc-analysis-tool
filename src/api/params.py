from datetime import date as date_cls
from fastapi import HTTPException, Query

DEFAULT_LIMIT = 20
MAX_LIMIT = 365

LIMIT_PARAM = Query(
    DEFAULT_LIMIT,
    ge=1,
    le=MAX_LIMIT,
    description=(
        f"Max rows returned, the most recent ones within the window "
        f"(default {DEFAULT_LIMIT}, max. {MAX_LIMIT})"
    ),
)
DATE_PARAM = Query(None, description="Return only this date, YYYY-MM-DD")
START_PARAM = Query(
    None, description="Window start, inclusive (YYYY-MM-DD)"
)
END_PARAM = Query(None, description="Window end, inclusive (YYYY-MM-DD)")


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


def parse_range(
    date: str | None, start: str | None, end: str | None
) -> tuple[str | None, str | None, str | None]:
    """Validate the ``?date=`` / ``?start=`` / ``?end=`` window of a table endpoint.

    ``?date=`` selects a single day and cannot be combined with a range, so the
    three filters never contradict each other.

    :param date: single day, YYYY-MM-DD
    :param start: inclusive window start, YYYY-MM-DD
    :param end: inclusive window end, YYYY-MM-DD
    :return: the three values, ISO normalized, with empty ones as None
    :raises HTTPException: 422 on a non-ISO value, an inverted range, or
        ``date`` combined with ``start``/``end``
    """
    day = parse_date(date, "date") if date else None
    first = parse_date(start, "start") if start else None
    last = parse_date(end, "end") if end else None

    if day and (first or last):
        raise HTTPException(
            status_code=422,
            detail="date cannot be combined with start/end; use the range only",
        )
    if first and last and first > last:
        raise HTTPException(
            status_code=422, detail=f"start {first} is after end {last}"
        )
    return day, first, last
