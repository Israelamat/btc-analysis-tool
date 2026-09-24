"""Report the time range of every table stored in the local SQLite database.

Reads each stored table and prints its row count plus, whenever a usable
date column exists, the min/max date and the span in days. Tables that are
empty, lack a date column or fail to load are reported with the specific
reason instead of aborting the whole run.
"""

import sqlite3

import pandas as pd

from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

DATE_COLUMN = "date"

GROUP_BY = {
    "fred_series": "series_id",
    "google_trends": "keyword",
}


def _load_table(db: DatabaseManager, table: str) -> tuple[pd.DataFrame | None, str]:
    """Load a full table, returning (frame, status)."""
    try:
        with sqlite3.connect(db.db_path) as conn:
            frame = pd.read_sql_query(f"SELECT * FROM {table}", conn)
        return frame, "ok"
    except sqlite3.Error as exc:
        return None, f"load_error: {exc}"


def _coverage_record(table: str, label: str, frame: pd.DataFrame) -> dict[str, object]:
    rows = len(frame)
    if rows == 0:
        logger.warning(f"table[{table}] is empty; no time range available")
        return {
            "table": table,
            "label": label,
            "rows": rows,
            "min_date": None,
            "max_date": None,
            "span_days": None,
            "status": "empty",
        }

    if DATE_COLUMN not in frame.columns:
        logger.warning(
            f"table[{table}] has no '{DATE_COLUMN}' column; row count reported only"
        )
        return {
            "table": table,
            "label": label,
            "rows": rows,
            "min_date": None,
            "max_date": None,
            "span_days": None,
            "status": "no_date",
        }

    dates = pd.to_datetime(frame[DATE_COLUMN], format="ISO8601", errors="coerce").dropna()
    if dates.empty:
        logger.warning(
            f"table[{table}] has no valid '{DATE_COLUMN}' values; row count reported only"
        )
        return {
            "table": table,
            "label": label,
            "rows": rows,
            "min_date": None,
            "max_date": None,
            "span_days": None,
            "status": "no_date",
        }

    span = int((dates.max() - dates.min()).days)
    return {
        "table": table,
        "label": label,
        "rows": rows,
        "min_date": dates.min().date(),
        "max_date": dates.max().date(),
        "span_days": span,
        "status": "ok",
    }


def run_report() -> None:
    db = DatabaseManager()
    print(f"\n=== Data time range by table ({db.db_path}) ===")

    records = []
    for table in db.TABLE_NAMES:
        frame, load_status = _load_table(db, table)
        if frame is None:
            logger.error(f"table[{table}] failed to load: {load_status}")
            records.append(
                {
                    "table": table,
                    "label": "-",
                    "rows": None,
                    "min_date": None,
                    "max_date": None,
                    "span_days": None,
                    "status": load_status,
                }
            )
            continue

        if frame.empty:
            records.append(_coverage_record(table, "-", frame))
            continue

        group_col = GROUP_BY.get(table)
        if group_col and group_col in frame.columns:
            for key in sorted(frame[group_col].unique()):
                subset = frame[frame[group_col] == key]
                records.append(_coverage_record(table, f"{group_col}={key}", subset))
        else:
            records.append(_coverage_record(table, "-", frame))

    report = pd.DataFrame(records)
    print(report.to_string(index=False))

    ok = report[report["status"] == "ok"]
    fallback = report[report["status"] != "ok"]

    print(f"\nTables with a usable date range: {len(ok)}/{len(report)}")
    if not fallback.empty:
        print(f"Tables using a fallback ({len(fallback)}):")
        for _, row in fallback.iterrows():
            print(f"- {row['table']}: {row['status']}")

    if not ok.empty:
        spans = ok["span_days"].astype(int)
        print(f"Longest span: {spans.max()} days, shortest: {spans.min()} days")