import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
import pandas as pd
from src.analytics.backtest import (
    ZONE_BUCKETS,
    load_metrics_with_forwards,
    summarize,
)
from src.analytics.calibrate import collect_calibration
from src.analytics.scoring import BTCAcumulationScorer
from src.api.cache import TTLCache
from src.api.serializers import date_str, jsonable, records
from src.config import Config
from src.fetchers.pipeline import ZONE_ACTION, zone_history_stats
from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

CORRELATION_HORIZON = 90
DEFAULT_ROW_LIMIT = 20

COMPONENT_META = {
    "google_trends": {
        "tag": "Contrarian",
        "description": (
            "LOW search interest is better (contrarian). This is the strongest signal."
        ),
        "contrarian": True,
    },
    "macd": {
        "tag": "Momentum",
        "description": "Bullish momentum from the MACD histogram.",
        "contrarian": False,
    },
    "dxy": {
        "tag": "Weak dollar",
        "description": "A weak (bearish) dollar is better for risk assets.",
        "contrarian": True,
    },
    "m2": {
        "tag": "Liquidity",
        "description": (
            "High year-over-year M2 growth means more liquidity in the market."
        ),
        "contrarian": False,
    },
    "ema_200": {
        "tag": "Valuation",
        "description": "A price below the EMA-200 is cheaper.",
        "contrarian": True,
    },
    "fear_greed": {
        "tag": "Contrarian",
        "description": "Extreme fear is better (contrarian).",
        "contrarian": True,
    },
    "rsi": {
        "tag": "Oversold",
        "description": "Oversold (low RSI) is better for accumulating.",
        "contrarian": True,
    },
}

M2_SERIES_ID = "M2SL"
TRENDS_KEYWORD = "bitcoin"

TABLE_SOURCES: dict[str, dict] = {
    "scores": {
        "table": "metrics_history",
        "columns": (
            "date",
            "btc_price",
            "ema_200",
            "rsi_14",
            "fear_greed",
            "m2_yoy",
            "sp500",
            "nasdaq",
            "dxy",
            "macd_hist",
            "google_trends",
            "total_score",
            "zone",
        ),
        "load": lambda db: db.load_metrics_history(),
    },
    "klines": {
        "table": "btc_klines",
        "columns": ("date", "open", "high", "low", "close", "volume"),
        "load": lambda db: db.load_btc_klines(),
    },
    "indicators": {
        "table": "btc_indicators",
        "columns": (
            "date",
            "ema_200",
            "rsi_14",
            "macd",
            "macd_signal",
            "macd_hist",
        ),
        "load": lambda db: db.load_btc_indicators(),
    },
    "fear-greed": {
        "table": "fear_greed_history",
        "columns": ("date", "value", "classification"),
        "load": lambda db: db.load_fear_greed(),
    },
    "fred": {
        "table": "fred_series",
        "columns": ("date", "value", "series_id"),
        "load": lambda db: db.load_fred_series(M2_SERIES_ID),
        "extra": {"series_id": M2_SERIES_ID},
    },
    "stocks": {
        "table": "stock_history",
        "columns": ("date", "sp500", "nasdaq", "dxy"),
        "load": lambda db: db.load_stock_history(),
    },
    "google-trends": {
        "table": "google_trends",
        "columns": ("date", "value", "keyword"),
        "load": lambda db: db.load_google_trends(TRENDS_KEYWORD),
        "extra": {"keyword": TRENDS_KEYWORD},
    },
}

ZONE_LABELS = tuple(label for _, label in ZONE_BUCKETS)
ZONE_RANK = {label: rank for rank, label in enumerate(ZONE_LABELS)}

SCORE_TREND_RANGE_DAYS = 90
PERCENTILE_WINDOW_DAYS = 365

_HORIZON_PATTERN = re.compile(r"^(\d+)d$")

_cache = TTLCache()


@lru_cache(maxsize=1)
def get_db() -> DatabaseManager:
    """Shared database handle (schema init runs once per process)."""
    return DatabaseManager()


def clear_cache() -> None:
    """Drop every memoized backtest/coverage result."""
    _cache.clear()

def table_series(
    source: str,
    limit: int = DEFAULT_ROW_LIMIT,
    date: str | None = None,
) -> dict:
    """Rows of one stored table, oldest first.

    Every table endpoint goes through here, so they all accept the same window
    and answer the same way: ``?limit=`` returns the most recent rows, while
    ``?date=`` narrows the result to a single day.

    :param source: key of :data:`TABLE_SOURCES`
    :param limit: max rows to return, the most recent ones
    :param date: when given, only the row of that date
    :raises KeyError: when the source name is unknown
    """
    if source not in TABLE_SOURCES:
        raise KeyError(source)

    spec = TABLE_SOURCES[source]
    frame = spec["load"](get_db())
    payload = {
        "source": source,
        "table": spec["table"],
        "date": date,
        "count": 0,
        "rows": [],
    }
    if frame is None or frame.empty:
        return payload

    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"]).sort_values("date")

    if date:
        frame = frame[frame["date"] == pd.Timestamp(date)]
    elif limit:
        frame = frame.tail(int(limit))

    keep = [column for column in spec["columns"] if column in frame.columns]
    out = frame[keep] if keep else frame
    if spec.get("extra"):
        out = out.assign(**spec["extra"])

    rows = records(out)
    payload["count"] = len(rows)
    payload["rows"] = rows
    return payload

def _safe_components(raw) -> dict:
    """Parse a stored components JSON blob, returning {} when unusable."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _components_from_row(record) -> dict:
    """Per-signal scores for a record, recomputed when missing or corrupt.

    Accepts a stored ``metrics_history`` row or a plain record dict.
    """
    parsed = _safe_components(record.get("components"))
    if parsed:
        return {key: float(value) for key, value in parsed.items()}

    logger.warning("No usable components stored; recomputing from raw columns")
    return BTCAcumulationScorer().calculate(
        current_price=record.get("btc_price"),
        ema_200=record.get("ema_200"),
        rsi=record.get("rsi_14"),
        fear_greed=record.get("fear_greed"),
        m2_yoy=record.get("m2_yoy"),
        dxy_status=record.get("dxy"),
        macd_hist=record.get("macd_hist"),
        google_trends=record.get("google_trends"),
    )["components"]


def _number(value, default: float = 0.0) -> float:
    """Coerce a stored column into a finite float, using `default` otherwise."""
    clean = jsonable(value)
    if clean is None:
        return default
    try:
        return float(clean)
    except (TypeError, ValueError):
        return default


def _optional_number(value) -> float | None:
    """Coerce a stored column into a float, or None when it is missing."""
    clean = jsonable(value)
    if clean is None:
        return None
    try:
        return float(clean)
    except (TypeError, ValueError):
        return None


def _optional_int(value) -> int | None:
    """Coerce a stored column into an int, or None when it is missing."""
    number = _optional_number(value)
    return None if number is None else int(round(number))


def report_from_record(record: dict, components: dict | None = None) -> dict:
    """Build the dashboard report contract from a plain record dict.

    Accepts both a stored ``metrics_history`` row and a live pipeline record.

    :param record: mapping with the metrics columns
    :param components: per-signal scores; parsed from the record when omitted
    """
    zone = str(jsonable(record.get("zone")) or "")
    action, ratio = ZONE_ACTION.get(zone, ("NO ACTION DEFINED", 0.0))
    scores = components or _components_from_row(record)
    return {
        "date": date_str(record.get("date")),
        "btc_price": _number(record.get("btc_price")),
        "ema_200": _number(record.get("ema_200")),
        "rsi_14": _number(record.get("rsi_14")),
        "fear_greed": int(_number(record.get("fear_greed"))),
        "m2_yoy": _number(record.get("m2_yoy")),
        "sp500": jsonable(record.get("sp500")),
        "nasdaq": jsonable(record.get("nasdaq")),
        "dxy": str(jsonable(record.get("dxy")) or "neutral"),
        "macd_hist": _number(record.get("macd_hist")),
        "google_trends": _number(record.get("google_trends")),
        "total_score": int(_number(record.get("total_score"))),
        "zone": zone,
        "components": jsonable(scores),
        "action": action,
        "ratio": ratio,
        "zone_history": (
            jsonable(zone_history_stats(get_db(), zone)) if zone else None
        ),
    }


def latest_report() -> dict | None:
    """The most recent stored report, i.e. what the last pipeline run saved."""
    history = get_db().load_latest_metrics(limit=1)
    if history.empty:
        return None
    return report_from_record(history.iloc[0].to_dict())

def _zone_runs(frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse the daily series into consecutive runs of the same zone."""
    zones = frame["zone"].fillna("").astype(str)
    tagged = frame.assign(_run=zones.ne(zones.shift()).cumsum())
    grouped = tagged.groupby("_run", sort=True)
    return pd.DataFrame(
        {
            "zone": grouped["zone"].first(),
            "start": grouped["date"].min(),
            "end": grouped["date"].max(),
            "days": grouped["date"].size(),
            "score": grouped["total_score"].last(),
        }
    ).reset_index(drop=True)


def _run_payload(run: pd.Series) -> dict:
    """One zone run: which zone, from when to when, and for how long."""
    return {
        "zone": str(run.get("zone") or ""),
        "start": date_str(run.get("start")),
        "end": date_str(run.get("end")),
        "days": int(run.get("days") or 0),
        "score": _optional_int(run.get("score")),
    }


def _transitions_from_runs(runs: pd.DataFrame) -> list[dict]:
    """Zone changes in chronological order, with the direction of each move."""
    out: list[dict] = []
    for position in range(1, len(runs)):
        previous = runs.iloc[position - 1]
        current = runs.iloc[position]
        from_zone = str(previous["zone"] or "")
        to_zone = str(current["zone"] or "")
        out.append(
            {
                "date": date_str(current["start"]),
                "from_zone": from_zone,
                "to_zone": to_zone,
                "direction": (
                    "up"
                    if ZONE_RANK.get(to_zone, 0) < ZONE_RANK.get(from_zone, 0)
                    else "down"
                ),
                "days_in_previous": int(previous["days"] or 0),
                "previous_end": date_str(previous["end"]),
            }
        )
    return out


def _zone_distribution(runs: pd.DataFrame, total_days: int) -> list[dict]:
    """Days, share of history and episode length per zone, best zone first."""
    out: list[dict] = []
    for zone in ZONE_LABELS:
        subset = runs[runs["zone"] == zone]
        if subset.empty:
            out.append(
                {
                    "zone": zone,
                    "days": 0,
                    "share_pct": 0.0,
                    "episodes": 0,
                    "mean_episode_days": None,
                    "median_episode_days": None,
                    "first_seen": None,
                    "last_seen": None,
                }
            )
            continue
        days = int(subset["days"].sum())
        out.append(
            {
                "zone": zone,
                "days": days,
                "share_pct": round(days / total_days * 100, 1) if total_days else 0.0,
                "episodes": int(len(subset)),
                "mean_episode_days": round(float(subset["days"].mean()), 1),
                "median_episode_days": float(subset["days"].median()),
                "first_seen": date_str(subset["start"].min()),
                "last_seen": date_str(subset["end"].max()),
            }
        )
    return out


def _zone_thresholds(score: float | None, zone: str) -> dict:
    """Score points needed to reach the zone above and the one below.

    Both boundaries are the *current* zone's own edges: its ceiling opens the
    better zone and its floor hands over to the worse one. Reading the better
    zone's floor for `up` and the worse zone's floor for `down` is what used to
    report a 32-point cushion when only 12 were left, and an infinite one in the
    Neutral zone (whose worse neighbour is the ``-inf`` Selling bucket).
    """
    if score is None or zone not in ZONE_RANK:
        return {"score": None, "zone": zone, "up": None, "down": None}

    index = ZONE_RANK[zone]
    floor = ZONE_BUCKETS[index][0]
    better = ZONE_BUCKETS[index - 1] if index > 0 else None
    worse = ZONE_BUCKETS[index + 1] if index < len(ZONE_LABELS) - 1 else None

    return {
        "score": int(round(score)),
        "zone": zone,
        "up": (
            {
                "zone": better[1],
                "min_score": better[0],
                "points_needed": max(round(better[0] - score, 1), 0.0),
            }
            if better
            else None
        ),
        "down": (
            {
                "zone": worse[1],
                "below_score": floor,
                "headroom": max(round(score - floor, 1), 0.0),
            }
            if worse
            else None
        ),
    }


def _score_trend(frame: pd.DataFrame) -> dict:
    """How the total score moved over the last days and its recent range."""
    scores = pd.to_numeric(frame["total_score"], errors="coerce").dropna()
    if scores.empty:
        return {
            "current": None,
            "change_7d": None,
            "change_30d": None,
            "min_90d": None,
            "max_90d": None,
        }

    current = int(round(float(scores.iloc[-1])))

    def change(days: int) -> int | None:
        if len(scores) <= days:
            return None
        return int(round(current - float(scores.iloc[-1 - days])))

    window = scores.iloc[-SCORE_TREND_RANGE_DAYS:]
    return {
        "current": current,
        "change_7d": change(7),
        "change_30d": change(30),
        "min_90d": int(window.min()),
        "max_90d": int(window.max()),
    }


def _price_context(last: pd.Series) -> dict:
    """Where the last stored price sits: vs EMA-200, vs ATH, over the last year."""
    klines = get_db().load_btc_klines()
    if klines.empty or "close" not in klines.columns:
        return {}

    frame = klines.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    close = (
        frame.dropna(subset=["date", "close"])
        .sort_values("date")
        .set_index("date")["close"]
        .astype(float)
    )
    if close.empty:
        return {}

    last_close = float(close.iloc[-1])
    ath = float(close.max())
    year = close[close.index >= close.index.max() - timedelta(days=PERCENTILE_WINDOW_DAYS)]

    def change(days: int) -> float | None:
        if len(close) <= days:
            return None
        past = float(close.iloc[-days - 1])
        return round((last_close / past - 1) * 100, 2) if past else None

    percentile = None
    if len(year) > 1 and float(year.max()) != float(year.min()):
        percentile = round(float((year < last_close).mean() * 100), 1)

    return {
        "price": round(last_close, 2),
        "as_of": date_str(close.index[-1]),
        "vs_ema_200_pct": _pct_vs(last_close, last.get("ema_200")),
        "ath": round(ath, 2),
        "ath_date": date_str(close.idxmax()),
        "drawdown_from_ath_pct": round((last_close / ath - 1) * 100, 1) if ath else None,
        "percentile_365d": percentile,
        "change_7d_pct": change(7),
        "change_30d_pct": change(30),
        "change_90d_pct": change(90),
    }


def _pct_vs(value: float, reference) -> float | None:
    """Percentage difference between two stored numbers, or None."""
    base = _optional_number(reference)
    if not base:
        return None
    return round((value / base - 1) * 100, 1)


def zone_context(transitions: int = 8) -> dict | None:
    """Where the market sits inside its score zone, with its price context.

    The daily series collapses into runs of the same zone, which answers the
    questions the dashboard asks: how long we have been here, what it took to
    leave the previous zone, how much score separates us from the next one and
    how rare this zone is over the stored history.

    :param transitions: how many recent zone changes to include
    :return: dict with the current run, thresholds, price context, per-zone
        distribution and the recent transitions, or None when no score is
        stored yet
    """
    frame = _filter_window(get_db().load_metrics_history())
    if frame.empty or "zone" not in frame.columns:
        return None

    runs = _zone_runs(frame)
    if runs.empty:
        return None

    last = frame.iloc[-1]
    zone = str(last.get("zone") or "")
    score = _optional_number(last.get("total_score"))
    action, ratio = ZONE_ACTION.get(zone, ("NO ACTION DEFINED", 0.0))
    current = runs.iloc[-1]
    changes = _transitions_from_runs(runs)

    return {
        "current": {
            "date": date_str(last.get("date")),
            "zone": zone,
            "score": _optional_int(score),
            "action": action,
            "ratio": ratio,
            "streak_days": int(current["days"] or 0),
            "streak_start": date_str(current["start"]),
            "zone_history": jsonable(zone_history_stats(get_db(), zone)) if zone else None,
            "score_trend": _score_trend(frame),
        },
        "previous": _run_payload(runs.iloc[-2]) if len(runs) > 1 else None,
        "thresholds": _zone_thresholds(score, zone),
        "price_context": _price_context(last),
        "distribution": _zone_distribution(runs, int(len(frame))),
        "transitions": changes[-transitions:] if transitions else [],
        "sample": {
            "start": date_str(frame["date"].min()),
            "end": date_str(frame["date"].max()),
            "days": int(len(frame)),
            "episodes": int(len(runs)),
        },
    }

def macro_snapshot() -> dict:
    """Latest stored value of every macro / sentiment source."""
    db = get_db()
    latest = db.load_latest_metrics(limit=1)
    row = latest.iloc[0] if not latest.empty else None

    fear_greed = db.load_fear_greed()
    fred = db.load_fred_series(M2_SERIES_ID)
    stocks = db.load_stock_history()
    trends = db.load_google_trends(TRENDS_KEYWORD)

    def tail(frame: pd.DataFrame, column: str):
        if frame.empty or column not in frame.columns:
            return None
        return jsonable(frame.iloc[-1].get(column))

    def value(column: str):
        return jsonable(row.get(column)) if row is not None else None

    return {
        "as_of": date_str(row.get("date")) if row is not None else None,
        "fear_greed": {
            "value": value("fear_greed"),
            "classification": tail(fear_greed, "classification"),
            "history_start": (
                date_str(fear_greed["date"].iloc[0]) if not fear_greed.empty else None
            ),
        },
        "m2": {
            "series_id": M2_SERIES_ID,
            "yoy": value("m2_yoy"),
            "level": tail(fred, "value"),
            "as_of": date_str(fred["date"].iloc[-1]) if not fred.empty else None,
        },
        "stocks": {
            "sp500": value("sp500"),
            "nasdaq": value("nasdaq"),
            "dxy_trend": str(value("dxy") or "neutral"),
            "dxy_level": tail(stocks, "dxy"),
        },
        "google_trends": {
            "keyword": TRENDS_KEYWORD,
            "value": value("google_trends"),
            "as_of": date_str(trends["date"].iloc[-1]) if not trends.empty else None,
        },
    }

def _backtest_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    return _cache.get_or_set(
        "frames", lambda: load_metrics_with_forwards(get_db()), ttl_seconds=300
    )


def _horizon_sort_key(horizon: str) -> int:
    match = _HORIZON_PATTERN.match(horizon)
    return int(match.group(1)) if match else 0


def _by_horizon(rows: list[dict]) -> list[dict]:
    """Reshape wide summary rows (``mean_90d``) into one record per horizon.

    The horizon keeps the ``d`` suffix it already has in the column names, so
    ``mean_90d`` becomes ``horizon='90d'``.
    """
    out: list[dict] = []
    for row in rows:
        by_horizon: dict[str, dict] = {}
        for key, value in row.items():
            if key in ("zone", "n") or "_" not in key:
                continue
            metric, horizon = key.rsplit("_", 1)
            by_horizon.setdefault(horizon, {})[metric] = value

        for horizon in sorted(by_horizon, key=_horizon_sort_key):
            out.append(
                {
                    "zone": row.get("zone"),
                    "n": row.get("n"),
                    "horizon": horizon,
                    **by_horizon[horizon],
                }
            )
    return out


def backtest_zones() -> dict:
    """Forward return stats per zone and horizon, plus the score correlation."""
    metrics, klines = _backtest_frames()
    if metrics.empty or klines.empty:
        return {"zones": [], "correlation": None, "sample": {}}

    correlation = None
    comparable = metrics.dropna(
        subset=["total_score", f"ret_{CORRELATION_HORIZON}d"]
    )
    if len(comparable) >= 10:
        value = comparable["total_score"].corr(
            comparable[f"ret_{CORRELATION_HORIZON}d"]
        )
        correlation = None if value != value else round(float(value), 4)

    return {
        "zones": _by_horizon(records(summarize(metrics))),
        "correlation": correlation,
        "correlation_horizon_days": CORRELATION_HORIZON,
        "sample": {
            "start": date_str(metrics["date"].min()),
            "end": date_str(metrics["date"].max()),
            "days": int(len(metrics)),
        },
    }


def calibration() -> dict:
    """Per-component diagnostic: does the sub-score predict the forward return?

    The JSON version of ``python -m src.analytics.calibrate``. A component earns
    its weight when its 0-100 sub-score correlates positively with the forward
    return, which is how the weights in ``Config.SCORE_WEIGHTS`` were chosen.

    Each component is joined with its live weight and semantics, so the UI can
    show "0.60 weight, +0.267 correlation" without a second request.
    """
    metrics, klines = _backtest_frames()
    if metrics.empty or klines.empty:
        report = collect_calibration(pd.DataFrame())
    else:
        report = _cache.get_or_set(
            "calibration", lambda: collect_calibration(metrics), ttl_seconds=900
        )

    weights = dict(BTCAcumulationScorer().weights)
    for item in report["components"]:
        key = item["key"]
        item["weight"] = round(weights.get(key, 0.0), 4)
        item["tag"] = COMPONENT_META.get(key, {}).get("tag")
        item["description"] = COMPONENT_META.get(key, {}).get("description")
        item["contrarian"] = COMPONENT_META.get(key, {}).get("contrarian")

    report["note"] = (
        "Components are sorted by correlation, best predictor first. A positive "
        "correlation justifies the weight; `noise` (|r| < 0.05) means the weight "
        "is carried by convention rather than evidence."
    )
    return report


def model_config() -> dict:
    """Weights, zone thresholds and buy actions of the scoring model."""
    weights = dict(BTCAcumulationScorer().weights)
    zones = []
    for threshold, label in ZONE_BUCKETS:
        action, ratio = ZONE_ACTION.get(label, ("NO ACTION DEFINED", 0.0))
        zones.append(
            {
                "zone": label,
                "min_score": None if threshold == float("-inf") else threshold,
                "action": action,
                "ratio": ratio,
            }
        )

    return {
        "weights": weights,
        "zones": zones,
        "actions": {
            zone: {"action": action, "ratio": ratio}
            for zone, (action, ratio) in ZONE_ACTION.items()
        },
        "components": [
            {
                "key": key,
                "weight": round(weights.get(key, 0.0), 4),
                "tag": meta["tag"],
                "description": meta["description"],
                "contrarian": meta["contrarian"],
            }
            for key, meta in COMPONENT_META.items()
        ],
    }


def health() -> dict:
    """Service and database status."""
    db = get_db()
    latest = db.load_latest_metrics(limit=1)
    row = latest.iloc[0] if not latest.empty else None
    return {
        "status": "ok" if row is not None else "degraded",
        "database": "connected",
        "db_path": db.db_path,
        "tables": db.table_counts(),
        "latest_score_date": date_str(row.get("date")) if row is not None else None,
        "latest_score": jsonable(row.get("total_score")) if row is not None else None,
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

def _filter_window(
    frame: pd.DataFrame,
    days: int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Slice a frame by a trailing day count and/or explicit ISO dates."""
    if frame is None or frame.empty:
        return pd.DataFrame()

    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"]).sort_values("date")

    if days:
        out = out[out["date"] >= out["date"].max() - timedelta(days=int(days))]
    if start:
        out = out[out["date"] >= pd.Timestamp(start)]
    if end:
        out = out[out["date"] <= pd.Timestamp(end)]
    return out


def dashboard(days: int = 90) -> dict:
    """One payload with everything the dashboard needs on first paint.

    Bundles the report, the zone context, the macro snapshot, the model config,
    the service health, the empirical validation of the score and a short
    score/price series, so the frontend does a single request instead of
    chasing a dozen of them.

    :param days: length of the trailing score/price series
    :return: dict with the same sections the individual endpoints return
    """
    report = latest_report()
    context = zone_context()
    history = _filter_window(get_db().load_metrics_history(), days=days)
    prices = _filter_window(get_db().load_btc_klines(), days=days)

    series = pd.DataFrame()
    if not history.empty and not prices.empty:
        series = history[["date", "total_score", "zone"]].merge(
            prices[["date", "close"]], on="date", how="left"
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "report": {**report, "source": "stored"} if report is not None else None,
        "zone": context,
        "macro": macro_snapshot(),
        "config": model_config(),
        "backtest": backtest_zones(),
        "calibration": calibration(),
        "health": health(),
        "history": {
            "days": int(days),
            "count": len(records(series)),
            "rows": records(series),
        },
    }
