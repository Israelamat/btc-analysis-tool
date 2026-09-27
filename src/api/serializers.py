"""Turn pandas / numpy values into JSON-safe Python builtins.

FastAPI cannot serialize ``NaN``, ``numpy`` scalars or ``Timestamp`` objects,
and ``NaN`` is not valid JSON either, so every value that leaves the API goes
through :func:`jsonable`. Missing numbers become ``null`` instead of ``NaN``.
"""

import math
from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd

SEQUENCE_TYPES = (list, tuple, set, frozenset, np.ndarray, pd.Series, pd.Index)


def date_str(value: Any) -> str | None:
    """Format any date-ish value as ``YYYY-MM-DD``."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.strftime("%Y-%m-%d")
    return None


def jsonable(value: Any) -> Any:
    """Recursively convert a value into something ``json.dumps`` accepts."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, SEQUENCE_TYPES):
        return [jsonable(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None

    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return value


def records(
    frame: pd.DataFrame,
    columns: tuple[str, ...] | None = None,
    date_column: str = "date",
) -> list[dict[str, Any]]:
    """Convert a DataFrame into JSON-safe dicts, dates as ``YYYY-MM-DD``."""
    if frame is None or frame.empty:
        return []
    if columns:
        selected = [column for column in columns if column in frame.columns]
        if selected:
            frame = frame[selected]
    out = jsonable(frame.to_dict(orient="records"))
    if date_column in frame.columns:
        for row in out:
            row[date_column] = date_str(row.get(date_column))
    return out


def frame_values(frame: pd.DataFrame) -> list[Any]:
    """Convert a single-column DataFrame into a JSON-safe list."""
    if frame is None or frame.empty:
        return []
    return [jsonable(value) for value in frame.iloc[:, 0].tolist()]
