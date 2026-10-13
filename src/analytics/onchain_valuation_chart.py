import argparse
import json
import os
import webbrowser
from datetime import datetime

import pandas as pd

from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_OUT = os.path.join("reports", "onchain_valuation.html")

CHART_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"
ANNOTATION_CDN = (
    "https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/"
    "chartjs-plugin-annotation.min.js"
)

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
  .meta { color: #64748b; font-size: .85rem; margin: 0 0 16px; }
  .cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
  .card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
          padding: 10px 16px; min-width: 130px; }
  .card .value { font-size: 1.35rem; font-weight: 700; }
  .card .label { font-size: .78rem; color: #64748b; }
  .chart-wrap { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
                padding: 12px; height: 50vh; min-height: 340px; margin-bottom: 16px; }
  .pos { color: #16a34a; font-weight: 600; }
  .neg { color: #dc2626; font-weight: 600; }
</style>
</head>
<body>
<h1>__TITLE__</h1>
<p class="meta">Generated __GENERATED__ &middot; __START__ &rarr; __END__ &middot;
   MVRV = Price/SMA-365 &middot; NUPL = 1 &minus; 1/MVRV</p>

<div class="cards">__CARDS__</div>

<div class="chart-wrap"><canvas id="price"></canvas></div>
<div class="chart-wrap"><canvas id="valuation"></canvas></div>

<script>
const DATA = __DATA__;

new Chart(document.getElementById('price'), {
  type: 'line',
  data: {
    labels: DATA.labels,
    datasets: [
      { label: 'BTC price (log)', data: DATA.price, yAxisID: 'y',
        borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.06)',
        borderWidth: 1.4, pointRadius: 0, tension: 0.08, spanGaps: true, order: 2 },
      { label: 'SMA-365', data: DATA.sma365, yAxisID: 'y',
        borderColor: '#a855f7', borderWidth: 1.6, borderDash: [6, 4],
        pointRadius: 0, tension: 0.08, spanGaps: true, order: 1 }
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
           ticks: { callback: (v) => '$' + Number(v).toLocaleString() } }
    },
    plugins: { legend: { labels: { usePointStyle: true } } }
  }
});

new Chart(document.getElementById('valuation'), {
  type: 'line',
  data: {
    labels: DATA.labels,
    datasets: [
      { label: 'MVRV (Price/SMA-365)', data: DATA.mvrv, yAxisID: 'y',
        borderColor: '#f59e0b', borderWidth: 1.5, pointRadius: 0,
        tension: 0.1, spanGaps: true },
      { label: 'NUPL', data: DATA.nupl, yAxisID: 'y1',
        borderColor: '#0d9488', borderWidth: 1.5, pointRadius: 0,
        tension: 0.1, spanGaps: true }
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    scales: {
      x: { ticks: { maxTicksLimit: 12, autoSkip: true, maxRotation: 0 },
           grid: { display: false } },
      y: { type: 'linear', position: 'left',
           title: { display: true, text: 'MVRV' },
           grid: { drawOnChartArea: false } },
      y1: { type: 'linear', position: 'right',
            title: { display: true, text: 'NUPL' },
            grid: { drawOnChartArea: false } }
    },
    plugins: {
      legend: { labels: { usePointStyle: true } },
      annotation: {
        annotations: {
          mvrv1: { type: 'line', yScaleID: 'y', yMin: 1, yMax: 1,
            borderColor: 'rgba(245,158,11,0.55)', borderWidth: 1, borderDash: [5, 4],
            label: { display: true, content: 'MVRV = 1', position: 'start' } },
          nupl0: { type: 'line', yScaleID: 'y1', yMin: 0, yMax: 0,
            borderColor: 'rgba(13,148,136,0.55)', borderWidth: 1, borderDash: [5, 4],
            label: { display: true, content: 'NUPL = 0', position: 'end' } }
        }
      }
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


def _cards_html(current: dict) -> str:
    """Summary cards for the latest valid valuation reading."""

    def card(label: str, value: str) -> str:
        return (
            f'<div class="card"><div class="value">{value}</div>'
            f'<div class="label">{label}</div></div>'
        )

    def money(value) -> str:
        return f"${value:,.2f}" if value is not None else "&mdash;"

    def number(value, digits: int = 4) -> str:
        return f"{value:.{digits}f}" if value is not None else "&mdash;"

    vs = current.get("vs_sma_pct")
    if vs is None:
        vs_html = "&mdash;"
    else:
        css = "pos" if vs >= 0 else "neg"
        vs_html = f'<span class="{css}">{vs:+.1f}%</span>'

    return "".join(
        [
            card("Date", current.get("date") or "&mdash;"),
            card("Close", money(current.get("close"))),
            card("SMA-365", money(current.get("sma_365"))),
            card("Price vs SMA-365", vs_html),
            card("MVRV", number(current.get("mvrv"))),
            card("NUPL", number(current.get("nupl"))),
        ]
    )


def build_payload(
    db: DatabaseManager,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Assemble everything the HTML template needs from btc_indicators."""
    frame = db.load_btc_indicators()
    if frame.empty:
        raise RuntimeError("btc_indicators is empty; run the indicators backfill first")

    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date")
    if start:
        frame = frame[frame["date"] >= pd.Timestamp(start)]
    if end:
        frame = frame[frame["date"] <= pd.Timestamp(end)]
    if frame.empty:
        raise RuntimeError("no rows in the requested date window")

    labels = [d.strftime("%Y-%m-%d") for d in frame["date"]]
    price = [_number(value) for value in frame["close"]]
    sma365 = [_number(value) for value in frame["sma_365"]]
    mvrv = [_number(value) for value in frame["mvrv"]]
    nupl = [_number(value) for value in frame["nupl"]]

    latest = frame.iloc[-1]
    for _, row in frame.iloc[::-1].iterrows():
        if _number(row.get("mvrv")) is not None:
            latest = row
            break

    close = _number(latest.get("close"))
    sma = _number(latest.get("sma_365"))
    vs_sma = round((close / sma - 1) * 100, 2) if close and sma else None

    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "start": labels[0],
        "end": labels[-1],
        "labels": labels,
        "price": price,
        "sma365": sma365,
        "mvrv": mvrv,
        "nupl": nupl,
        "current": {
            "date": latest["date"].strftime("%Y-%m-%d"),
            "close": close,
            "sma_365": sma,
            "vs_sma_pct": vs_sma,
            "mvrv": _number(latest.get("mvrv")),
            "nupl": _number(latest.get("nupl")),
        },
    }


def render_html(payload: dict) -> str:
    """Fill the static template with the serialized payload."""
    return (
        TEMPLATE.replace("__TITLE__", "BTC on-chain valuation (MVRV & NUPL)")
        .replace("__GENERATED__", payload["generated"])
        .replace("__START__", payload["start"])
        .replace("__END__", payload["end"])
        .replace("__CHART_CDN__", CHART_CDN)
        .replace("__ANNOTATION_CDN__", ANNOTATION_CDN)
        .replace("__CARDS__", _cards_html(payload["current"]))
        .replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    )


def generate(
    out: str = DEFAULT_OUT,
    open_browser: bool = False,
    start: str | None = None,
    end: str | None = None,
) -> str:
    """Build the payload, write the HTML file and return its path."""
    payload = build_payload(DatabaseManager(), start, end)
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(render_html(payload))

    logger.info(f"Valuation chart written to {out}")
    print(f"Valuation chart written to {out}")
    if open_browser:
        webbrowser.open(os.path.abspath(out))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render an interactive HTML chart of the BTC on-chain valuation "
            "(price vs SMA-365, MVRV and NUPL)"
        )
    )
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output HTML path")
    parser.add_argument("--start", default=None, help="Window start (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="Window end (YYYY-MM-DD)")
    parser.add_argument(
        "--open", action="store_true", help="Open the file in the default browser"
    )
    args = parser.parse_args()
    generate(
        out=args.out,
        open_browser=args.open,
        start=args.start,
        end=args.end,
    )


if __name__ == "__main__":
    main()
