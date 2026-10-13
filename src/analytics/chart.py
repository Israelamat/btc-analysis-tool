import argparse
import json
import os
import webbrowser
from datetime import datetime

import pandas as pd

from src.analytics.backtest import _load_klines, forward_return
from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

HIGH_ZONE = 80.0
SELLING_ZONE = 30.0
TABLE_HORIZONS = (7, 30, 90, 180)
DEFAULT_OUT = os.path.join("reports", "buy_points.html")
DEFAULT_HORIZON = 90

CHART_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"
ANNOTATION_CDN = (
    "https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/"
    "chartjs-plugin-annotation.min.js"
)

HIGH_COLOR = "#16a34a"
SELLING_COLOR = "#dc2626"
HIGH_BAND = "rgba(22, 163, 74, 0.10)"
SELLING_BAND = "rgba(220, 38, 38, 0.12)"

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script src="__CHART_CDN__"></script>
<script src="__ANNOTATION_CDN__"></script>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         margin: 0; padding: 24px; background: #f8fafc; color: #0f172a; }
  h1 { font-size: 1.4rem; margin: 0 0 4px; }
  h2 { font-size: 1.1rem; margin: 28px 0 8px; }
  .meta { color: #64748b; font-size: .85rem; margin: 0 0 16px; }
  .cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
  .card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
          padding: 10px 16px; min-width: 130px; }
  .card .value { font-size: 1.35rem; font-weight: 700; }
  .card .label { font-size: .78rem; color: #64748b; }
  .chart-wrap { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
                padding: 12px; height: 62vh; min-height: 420px; }
  table { border-collapse: collapse; width: 100%; font-size: .85rem; background: #fff;
          border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; }
  th, td { padding: 6px 10px; text-align: right; border-bottom: 1px solid #eef2f7; }
  th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
  thead th { background: #f1f5f9; position: sticky; top: 0; }
  .pos { color: #16a34a; font-weight: 600; }
  .neg { color: #dc2626; font-weight: 600; }
  .scroll { max-height: 46vh; overflow: auto; border-radius: 10px; }
</style>
</head>
<body>
<h1>__TITLE__</h1>
<p class="meta">Generated __GENERATED__ &middot; horizon __HORIZON__d &middot;
   green = High accumulation (score &ge; 80) &middot; red = Selling zone (score &lt; 30)</p>

<div class="cards">__CARDS__</div>

<div class="chart-wrap"><canvas id="main"></canvas></div>

<h2>High-accumulation episodes (__ENTRIES__)</h2>
<div class="scroll">
<table>
<thead><tr>
  <th>Entry</th><th>End</th><th>Days</th><th>Score max</th><th>Price in</th>
  <th>Price min</th><th>7d</th><th>30d</th><th>90d</th><th>180d</th>
</tr></thead>
<tbody>__ROWS__</tbody>
</table>
</div>

<script>
const DATA = __DATA__;

const annotations = {};
DATA.highBands.forEach((band, i) => {
  annotations['h' + i] = { type: 'box', xScaleID: 'x', yScaleID: 'y',
    xMin: band[0], xMax: band[1], yMin: DATA.yMin, yMax: DATA.yMax,
    backgroundColor: '__HIGH_BAND__', borderWidth: 0, drawTime: 'beforeDatasetsDraw' };
});
DATA.sellingBands.forEach((band, i) => {
  annotations['s' + i] = { type: 'box', xScaleID: 'x', yScaleID: 'y',
    xMin: band[0], xMax: band[1], yMin: DATA.yMin, yMax: DATA.yMax,
    backgroundColor: '__SELLING_BAND__', borderWidth: 0, drawTime: 'beforeDatasetsDraw' };
});

new Chart(document.getElementById('main'), {
  type: 'line',
  data: {
    labels: DATA.labels,
    datasets: [
      { label: 'BTC price (log)', data: DATA.price, yAxisID: 'y',
        borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.06)',
        borderWidth: 1.4, pointRadius: DATA.radius, pointHoverRadius: 7,
        pointHitRadius: 8, pointBackgroundColor: DATA.color,
        pointBorderColor: DATA.color, tension: 0.08, spanGaps: true, order: 3 },
      { label: 'Accumulation score', data: DATA.score, yAxisID: 'y1',
        borderColor: '#f59e0b', borderWidth: 1.4, pointRadius: 0,
        tension: 0.1, spanGaps: true, order: 1 }
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    scales: {
      x: { ticks: { maxTicksLimit: 12, autoSkip: true, maxRotation: 0 },
           grid: { display: false } },
      y: { type: 'logarithmic', position: 'left',
           title: { display: true, text: 'BTC price (USD, log)' },
           ticks: { callback: (v) => '$' + Number(v).toLocaleString() } },
      y1: { type: 'linear', min: 0, max: 100, position: 'right',
            title: { display: true, text: 'Score' },
            grid: { drawOnChartArea: false } }
    },
    plugins: {
      legend: { labels: { usePointStyle: true } },
      annotation: { annotations: annotations }
    }
  }
});
</script>
</body>
</html>
"""


def _number(value) -> float | None:
    """Coerce a stored value to float, mapping empty/NaN to None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _runs(dates: pd.DatetimeIndex, mask: list[bool]) -> list[tuple[int, int]]:
    """Inclusive (start, end) index pairs of every run of True in `mask`.

    A gap larger than one day splits a run so each market episode counts once.
    """
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for i, flag in enumerate(mask):
        if flag:
            if start is None:
                start = i
            elif (dates[i] - dates[i - 1]).days > 1:
                ranges.append((start, i - 1))
                start = i
        elif start is not None:
            ranges.append((start, i - 1))
            start = None
    if start is not None:
        ranges.append((start, len(mask) - 1))
    return ranges


def _episode(
    metrics: pd.DataFrame,
    klines: pd.DataFrame,
    dates: pd.DatetimeIndex,
    start: int,
    end: int,
) -> dict:
    """One High-accumulation episode with its entry price and forward returns."""
    window = metrics.iloc[start : end + 1]
    entry = dates[start]
    scores = pd.to_numeric(window["total_score"], errors="coerce")
    row = {
        "start": entry.strftime("%Y-%m-%d"),
        "end": dates[end].strftime("%Y-%m-%d"),
        "days": int(end - start + 1),
        "score_max": int(scores.max()),
        "price_in": round(float(window["btc_price"].iloc[0])),
        "price_min": round(float(window["btc_price"].min())),
    }
    for horizon in TABLE_HORIZONS:
        value = forward_return(klines, pd.DatetimeIndex([entry]), horizon).iloc[0]
        row[f"ret_{horizon}"] = _number(value)
    return row


def build_payload(db: DatabaseManager, horizon: int = DEFAULT_HORIZON) -> dict:
    """Assemble everything the HTML template needs from the stored history."""
    metrics = db.load_metrics_history()
    if metrics.empty:
        raise RuntimeError("metrics_history is empty; run the score backfill first")

    metrics["date"] = pd.to_datetime(metrics["date"])
    metrics = metrics.sort_values("date").reset_index(drop=True)

    klines = _load_klines(db)
    if klines.empty:
        raise RuntimeError("btc_klines is empty; run the BTC backfill first")

    dates = pd.DatetimeIndex(metrics["date"])
    price = [_number(value) for value in metrics["btc_price"]]
    score = [_number(value) for value in metrics["total_score"]]

    high_mask = [value is not None and value >= HIGH_ZONE for value in score]
    selling_mask = [value is not None and value < SELLING_ZONE for value in score]

    radius: list[int] = []
    color: list[str] = []
    for high, selling in zip(high_mask, selling_mask):
        if high:
            radius.append(5)
            color.append(HIGH_COLOR)
        elif selling:
            radius.append(5)
            color.append(SELLING_COLOR)
        else:
            radius.append(0)
            color.append("transparent")

    high_ranges = _runs(dates, high_mask)
    selling_ranges = _runs(dates, selling_mask)

    episodes = [_episode(metrics, klines, dates, a, b) for a, b in high_ranges]

    prices = [value for value in price if value is not None]
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "horizon": horizon,
        "labels": [d.strftime("%Y-%m-%d") for d in dates],
        "price": price,
        "score": score,
        "radius": radius,
        "color": color,
        "highBands": [
            [dates[a].strftime("%Y-%m-%d"), dates[b].strftime("%Y-%m-%d")]
            for a, b in high_ranges
        ],
        "sellingBands": [
            [dates[a].strftime("%Y-%m-%d"), dates[b].strftime("%Y-%m-%d")]
            for a, b in selling_ranges
        ],
        "yMin": min(prices) * 0.85,
        "yMax": max(prices) * 1.15,
        "episodes": episodes,
        "summary": _summary(klines, dates, episodes, horizon),
    }


def _summary(
    klines: pd.DataFrame,
    dates: pd.DatetimeIndex,
    episodes: list[dict],
    horizon: int,
) -> dict:
    """High-entry stats versus the all-days baseline for the chosen horizon."""
    baseline = forward_return(klines, dates, horizon).dropna()
    high = pd.Series([row[f"ret_{horizon}"] for row in episodes]).dropna()
    return {
        "horizon": horizon,
        "entries": len(episodes),
        "high_mean": round(float(high.mean()), 1) if not high.empty else None,
        "high_win": round(float((high > 0).mean() * 100), 1) if not high.empty else None,
        "base_mean": round(float(baseline.mean()), 1) if not baseline.empty else None,
        "base_win": (
            round(float((baseline > 0).mean() * 100), 1) if not baseline.empty else None
        ),
    }


def _cards_html(summary: dict) -> str:
    horizon = summary["horizon"]

    def fmt(value, suffix, pos_neg=False):
        if value is None:
            return "&mdash;"
        css = ""
        if pos_neg:
            css = "pos" if value >= 0 else "neg"
        return f'<span class="{css}">{value:+.1f}{suffix}</span>' if pos_neg else f"{value}{suffix}"

    def card(label: str, value: str) -> str:
        return f'<div class="card"><div class="value">{value}</div><div class="label">{label}</div></div>'

    return "".join(
        [
            card("High entries", str(summary["entries"])),
            card(f"High mean {horizon}d", fmt(summary["high_mean"], "%", True)),
            card(f"High win {horizon}d", fmt(summary["high_win"], "%")),
            card(f"All-days mean {horizon}d", fmt(summary["base_mean"], "%", True)),
            card(f"All-days win {horizon}d", fmt(summary["base_win"], "%")),
        ]
    )


def _rows_html(episodes: list[dict]) -> str:
    rows = []
    for episode in episodes:
        cells = []
        for horizon in TABLE_HORIZONS:
            value = episode[f"ret_{horizon}"]
            if value is None:
                cells.append("<td>&mdash;</td>")
            else:
                css = "pos" if value >= 0 else "neg"
                cells.append(f'<td class="{css}">{value:+.1f}%</td>')
        rows.append(
            "<tr>"
            f'<td>{episode["start"]}</td><td>{episode["end"]}</td>'
            f'<td>{episode["days"]}</td><td>{episode["score_max"]}</td>'
            f'<td>${episode["price_in"]:,}</td><td>${episode["price_min"]:,}</td>'
            + "".join(cells)
            + "</tr>"
        )
    return "\n".join(rows)


def render_html(payload: dict) -> str:
    """Fill the static template with the serialized payload."""
    return (
        TEMPLATE.replace("__TITLE__", "BTC accumulation buy points")
        .replace("__GENERATED__", payload["generated"])
        .replace("__HORIZON__", str(payload["horizon"]))
        .replace("__CHART_CDN__", CHART_CDN)
        .replace("__ANNOTATION_CDN__", ANNOTATION_CDN)
        .replace("__HIGH_BAND__", HIGH_BAND)
        .replace("__SELLING_BAND__", SELLING_BAND)
        .replace("__ENTRIES__", str(payload["summary"]["entries"]))
        .replace("__CARDS__", _cards_html(payload["summary"]))
        .replace("__ROWS__", _rows_html(payload["episodes"]))
        .replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    )


def generate(
    out: str = DEFAULT_OUT,
    horizon: int = DEFAULT_HORIZON,
    open_browser: bool = False,
) -> str:
    """Build the payload, write the HTML file and return its path."""
    payload = build_payload(DatabaseManager(), horizon)
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(render_html(payload))

    logger.info(f"Chart written to {out}")
    print(f"Chart written to {out}")
    if open_browser:
        webbrowser.open(os.path.abspath(out))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render an interactive HTML chart of the accumulation buy points"
    )
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output HTML path")
    parser.add_argument(
        "--horizon",
        type=int,
        default=DEFAULT_HORIZON,
        help="Forward-return horizon (days) used in the summary cards",
    )
    parser.add_argument(
        "--open", action="store_true", help="Open the file in the default browser"
    )
    args = parser.parse_args()
    generate(out=args.out, horizon=args.horizon, open_browser=args.open)


if __name__ == "__main__":
    main()
