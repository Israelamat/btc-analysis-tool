"""Validate the accumulation score against forward BTC returns.

For every day with a recorded score, computes the BTC return over the
following 7/30/90/180/365/730 calendar days and groups it by score zone, so
the contrarian "buy when cheap" hypothesis can be checked empirically. An
optional non-overlapping bootstrap section validates how much of the edge
survives on statistically independent samples.
"""

import argparse
import math

import numpy as np
import pandas as pd

from src.analytics.scoring import allocation_ratio
from src.storage.db_manager import DatabaseManager
from src.utils.logger import setup_logger

logger = setup_logger()

HORIZONS = (7, 30, 90, 180, 365)
CYCLE_HORIZONS = (365, 730)
RETURN_HORIZONS = tuple(sorted(set(HORIZONS) | set(CYCLE_HORIZONS)))
DRAWDOWN_HORIZONS = (90, 180)
CYCLE_DRAWDOWN_HORIZONS = (365, 730)
ALL_DRAWDOWN_HORIZONS = tuple(
    sorted(set(DRAWDOWN_HORIZONS) | set(CYCLE_DRAWDOWN_HORIZONS))
)
INDEPENDENT_HORIZONS = (30, 90, 180, 365, 730)
CYCLE_SPLIT = "2022-01-01"
DCA_CONTRIBUTION = 1000.0
DCA_MULTIPLIER_MIN = 0.5
DCA_MULTIPLIER_MAX = 1.5
INITIAL_CAPITAL = 10000.0
ZONE_BUCKETS = (
    (70.0, "High accumulation zone"),
    (50.0, "Moderate accumulation zone"),
    (30.0, "Neutral zone"),
    (float("-inf"), "Selling zone"),
)


def _bucket(score: pd.Series) -> pd.Series:
    """Map scores to the same zones used by the scorer."""
    out = pd.Series("Selling zone", index=score.index, dtype="object")
    for threshold, label in ZONE_BUCKETS:
        out[score >= threshold] = label
    return out


def _load_klines(db: DatabaseManager) -> pd.DataFrame:
    klines = db.load_btc_klines()
    if klines.empty:
        return pd.DataFrame(columns=["close", "date"])
    klines["date"] = pd.to_datetime(klines["date"])
    return klines.sort_values("date").set_index("date")


def forward_return(
    klines: pd.DataFrame, scored_dates: pd.DatetimeIndex, horizon: int
) -> pd.Series:
    """Return in % for each scored date, `horizon` calendar days later.

    The forward price is never forward-filled past the last candle and the
    full horizon must fit inside the data; otherwise the observation is NaN
    instead of a fabricated flat return.
    """
    future_dates = scored_dates + pd.Timedelta(days=horizon)
    future_close = klines["close"].reindex(future_dates, method="ffill")
    base_close = klines["close"].reindex(scored_dates, method="ffill")
    returns = (future_close.to_numpy() / base_close.to_numpy() - 1) * 100
    complete = future_dates <= klines.index.max()
    return pd.Series(returns, index=scored_dates).where(complete)


def forward_max_drawdown(
    klines: pd.DataFrame, scored_dates: pd.DatetimeIndex, horizon: int
) -> pd.Series:
    """Worst peak-to-trough decline (%) inside each forward `horizon`-day window.

    Unlike returns this captures the journey: a zone that ends green at 365d
    can still lose -40% before recovering. Negative values, lower is worse.
    """
    close = klines["close"].to_numpy(dtype=float)
    close_dates = klines.index
    last_date = close_dates.max()
    out = np.full(len(scored_dates), np.nan)
    for i, date in enumerate(scored_dates):
        target = date + pd.Timedelta(days=horizon)
        if target > last_date:
            continue
        start = close_dates.searchsorted(date, side="left")
        end = close_dates.searchsorted(target, side="right")
        window = close[start:end]
        if len(window) == 0:
            continue
        peak = np.maximum.accumulate(window)
        out[i] = float((window / peak - 1).min() * 100)
    return pd.Series(out, index=scored_dates)


def sample_independent(dates: pd.DatetimeIndex, horizon: int) -> pd.DatetimeIndex:
    """Keep dates spaced at least `horizon` days apart (non-overlapping picks)."""
    picks = []
    last = None
    for date in dates:
        if last is None or (date - last).days >= horizon:
            picks.append(date)
            last = date
    return pd.DatetimeIndex(picks)


def _bootstrap_replicates(
    values: pd.Series, stat, n_resamples: int, seed: int
) -> np.ndarray:
    """Bootstrap samples of `stat` over `values` (fixed seed for determinism)."""
    arr = values.to_numpy(dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return np.empty(0)
    rng = np.random.default_rng(seed)
    boot = np.empty(n_resamples)
    for i in range(n_resamples):
        boot[i] = stat(rng.choice(arr, size=arr.size, replace=True))
    return boot


def bootstrap_ci(
    values: pd.Series,
    stat=np.mean,
    n_resamples: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for `stat` over `values`."""
    boot = _bootstrap_replicates(values, stat, n_resamples, seed)
    if boot.size == 0:
        return np.nan, np.nan
    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def _probability_mean_negative(
    values: pd.Series, n_resamples: int = 2000, seed: int = 42
) -> float:
    """Fraction of bootstrapped means below zero (probability mean < 0)."""
    boot = _bootstrap_replicates(values, np.mean, n_resamples, seed)
    if boot.size == 0:
        return np.nan
    return float((boot < 0).mean())


def _episode_first_dates(frame: pd.DataFrame) -> pd.DatetimeIndex:
    """First date of every consecutive-day run for a single zone."""
    dates = pd.DatetimeIndex(frame["date"])
    picks = []
    last = None
    for date in dates:
        if last is None or (date - last).days > 1:
            picks.append(date)
        last = date
    return pd.DatetimeIndex(picks)


def _binomial_cdf(k: int, n: int) -> float:
    """P(X <= k) for X ~ Binomial(n, 0.5)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    total = sum(math.comb(n, j) * 0.5**n for j in range(k + 1))
    return min(total, 1.0)


def summarize(
    metrics: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS
) -> pd.DataFrame:
    rows = []
    for zone, group in metrics.groupby("zone", sort=False):
        row = {"zone": zone, "n": int(len(group))}
        for horizon in horizons:
            values = group[f"ret_{horizon}d"].dropna()
            if values.empty:
                continue
            row[f"mean_{horizon}d"] = round(float(values.mean()), 2)
            row[f"median_{horizon}d"] = round(float(values.median()), 2)
            row[f"win_rate_{horizon}d"] = round(float((values > 0).mean()) * 100, 1)
        rows.append(row)

    return _zone_order(pd.DataFrame(rows))


def summarize_drawdowns(
    metrics: pd.DataFrame, horizons: tuple[int, ...] = DRAWDOWN_HORIZONS
) -> pd.DataFrame:
    """Per-zone worst in-window drawdown (negative %, lower is worse)."""
    rows = []
    for zone, group in metrics.groupby("zone", sort=False):
        row = {"zone": zone, "n": int(len(group))}
        for horizon in horizons:
            values = group[f"dd_{horizon}d"].dropna()
            if values.empty:
                continue
            row[f"mean_dd_{horizon}d"] = round(float(values.mean()), 2)
            row[f"median_dd_{horizon}d"] = round(float(values.median()), 2)
            row[f"worst_dd_{horizon}d"] = round(float(values.min()), 2)
        rows.append(row)

    return _zone_order(pd.DataFrame(rows))


def _zone_order(frame: pd.DataFrame) -> pd.DataFrame:
    order = {label: index for index, (_, label) in enumerate(ZONE_BUCKETS)}
    if frame.empty:
        return frame
    return frame.sort_values("zone", key=lambda s: s.map(order))


def correlation_table(
    metrics: pd.DataFrame, horizons: tuple[int, ...] = RETURN_HORIZONS
) -> pd.DataFrame:
    """Score correlation with forward returns for every horizon.

    The same daily score is measured against 7/30/90/180/365/730d returns.
    A cycle model should improve as the horizon lengthens; a short-term timer
    should show the opposite.
    """
    rows = []
    for horizon in horizons:
        column = f"ret_{horizon}d"
        if column not in metrics.columns:
            continue
        sample = metrics.dropna(subset=["total_score", column])
        if len(sample) < 10:
            continue
        pearson = sample["total_score"].corr(sample[column])
        spearman = sample["total_score"].rank().corr(sample[column].rank())
        rows.append(
            {
                "horizon": f"{horizon}d",
                "n": int(len(sample)),
                "pearson": round(float(pearson), 3),
                "spearman": round(float(spearman), 3),
            }
        )
    return pd.DataFrame(rows)


def temporal_correlation_table(
    metrics: pd.DataFrame,
    split: str = CYCLE_SPLIT,
    horizons: tuple[int, ...] = CYCLE_HORIZONS,
) -> pd.DataFrame:
    """Cycle-horizon correlation before and after a temporal split.

    The weights were designed on the full sample, so this is a stability check,
    not a clean out-of-sample test: it answers whether the cycle relationship
    survives in the later part of the history.
    """
    dates = pd.to_datetime(metrics["date"])
    split_date = pd.Timestamp(split)
    rows = []
    for period, mask in (
        ("before_split", dates < split_date),
        ("after_split", dates >= split_date),
    ):
        subset = metrics.loc[mask]
        for horizon in horizons:
            column = f"ret_{horizon}d"
            if column not in subset.columns:
                continue
            sample = subset.dropna(subset=["total_score", column])
            if len(sample) < 10:
                continue
            pearson = sample["total_score"].corr(sample[column])
            spearman = sample["total_score"].rank().corr(sample[column].rank())
            rows.append(
                {
                    "period": period,
                    "horizon": f"{horizon}d",
                    "n": int(len(sample)),
                    "pearson": round(float(pearson), 3),
                    "spearman": round(float(spearman), 3),
                }
            )
    return pd.DataFrame(rows)


def _dca_path(prices: np.ndarray, contributions: np.ndarray) -> dict:
    """Simulate periodic buys and mark the portfolio to the last price."""
    units = contributions / prices
    cumulative_units = np.cumsum(units)
    invested = np.cumsum(contributions)
    value = cumulative_units * prices
    drawdown = value / np.maximum.accumulate(value) - 1.0
    total_units = float(cumulative_units[-1])
    total_invested = float(invested[-1])
    final_value = total_units * float(prices[-1])
    return {
        "months": int(len(prices)),
        "invested": total_invested,
        "units": total_units,
        "avg_cost": total_invested / total_units,
        "final_value": final_value,
        "roi_pct": (final_value / total_invested - 1.0) * 100,
        "max_dd_pct": float(drawdown.min() * 100),
    }


def monthly_dca_table(
    metrics: pd.DataFrame,
    contribution: float = DCA_CONTRIBUTION,
    min_multiplier: float = DCA_MULTIPLIER_MIN,
    max_multiplier: float = DCA_MULTIPLIER_MAX,
) -> pd.DataFrame:
    """Flat monthly DCA vs a score-scaled monthly DCA (0.5x-1.5x).

    The multiplier uses the previous day's score, so the buy decision never
    peeks at the same close it is executed on. An empty frame means there is
    not enough history for a meaningful comparison.
    """
    required = {"date", "btc_price", "total_score"}
    if metrics.empty or not required.issubset(metrics.columns):
        return pd.DataFrame()

    frame = metrics[["date", "btc_price", "total_score"]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.dropna(subset=["date", "btc_price"]).sort_values("date")
    frame = frame[frame["btc_price"] > 0]
    if frame.empty:
        return pd.DataFrame()

    frame["prior_score"] = frame["total_score"].shift(1)
    monthly = (
        frame.groupby(frame["date"].dt.to_period("M"), as_index=False)
        .first()
        .sort_values("date")
    )
    if len(monthly) < 2:
        return pd.DataFrame()

    score = monthly["prior_score"].fillna(50.0).clip(0, 100)
    multiplier = min_multiplier + (
        (max_multiplier - min_multiplier) * score / 100.0
    )
    prices = monthly["btc_price"].to_numpy(dtype=float)
    flat = _dca_path(prices, np.full(len(prices), contribution))
    scaled = _dca_path(
        prices, contribution * multiplier.to_numpy(dtype=float)
    )

    return pd.DataFrame(
        [
            {
                "months": flat["months"],
                "avg_multiplier": round(float(multiplier.mean()), 2),
                "flat_avg_cost": round(flat["avg_cost"], 0),
                "scaled_avg_cost": round(scaled["avg_cost"], 0),
                "cost_improvement_pct": (
                    round((flat["avg_cost"] / scaled["avg_cost"] - 1) * 100, 2)
                    if scaled["avg_cost"]
                    else np.nan
                ),
                "flat_invested": round(flat["invested"], 0),
                "scaled_invested": round(scaled["invested"], 0),
                "flat_roi_pct": round(flat["roi_pct"], 1),
                "scaled_roi_pct": round(scaled["roi_pct"], 1),
                "flat_max_dd_pct": round(flat["max_dd_pct"], 1),
                "scaled_max_dd_pct": round(scaled["max_dd_pct"], 1),
            }
        ]
    )


def cycle_playbook_table(
    metrics: pd.DataFrame, klines: pd.DataFrame
) -> pd.DataFrame:
    """Buy each High episode and sell at the first later Selling episode.

    Open buys (no later Selling episode) are marked to the latest close and
    reported as unrealized. Returns are percentages from entry to exit, so the
    win rate is the share of buys that ended in profit.
    """
    if metrics.empty or klines.empty:
        return pd.DataFrame()
    if not {"date", "zone"}.issubset(metrics.columns):
        return pd.DataFrame()

    frame = metrics[["date", "zone"]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date")
    buys = _episode_first_dates(
        frame[frame["zone"] == "High accumulation zone"]
    )
    sells = _episode_first_dates(frame[frame["zone"] == "Selling zone"])
    if buys.empty:
        return pd.DataFrame()

    close = klines["close"].astype(float)
    latest_close = float(close.iloc[-1])
    latest_date = close.index.max()
    rows = []
    for buy in buys:
        entry = close.reindex([buy], method="ffill").iloc[0]
        if pd.isna(entry) or entry <= 0:
            continue
        position = sells.searchsorted(buy, side="right")
        if position < len(sells):
            exit_date = sells[position]
            exit_price = close.reindex([exit_date], method="ffill").iloc[0]
            state = "Realized"
        else:
            exit_date = latest_date
            exit_price = latest_close
            state = "Unrealized"
        if pd.isna(exit_price):
            continue
        rows.append(
            {
                "state": state,
                "return_pct": (float(exit_price) / float(entry) - 1) * 100,
                "days": int((exit_date - buy).days),
            }
        )

    if not rows:
        return pd.DataFrame()

    trades = pd.DataFrame(rows)
    summary = []
    for state in ("Realized", "Unrealized"):
        subset = trades[trades["state"] == state]
        if subset.empty:
            continue
        returns = subset["return_pct"]
        summary.append(
            {
                "state": state,
                "trades": int(len(subset)),
                "win_rate_pct": round(float((returns > 0).mean() * 100), 1),
                "mean_return_pct": round(float(returns.mean()), 1),
                "median_return_pct": round(float(returns.median()), 1),
                "best_pct": round(float(returns.max()), 1),
                "worst_pct": round(float(returns.min()), 1),
                "avg_days": round(float(subset["days"].mean()), 0),
            }
        )
    return pd.DataFrame(summary)


def _bar(value: float, width: int = 20) -> str:
    """ASCII bar for a 0-100 percentage."""
    filled = int(round(max(0.0, min(100.0, value)) / 100 * width))
    return "#" * filled + "-" * (width - filled)


def playbook_validation(
    metrics: pd.DataFrame, klines: pd.DataFrame
) -> None:
    """Report realized and unrealized outcomes of the High->Selling cycle."""
    print("\n=== Cycle playbook: buy High accumulation, sell Selling zone ===")
    print(
        "One buy per High-accumulation episode; the first later Selling "
        "episode closes it. Open buys are marked to the latest close."
    )
    table = cycle_playbook_table(metrics, klines)
    if table.empty:
        print("Not enough cycle trades to summarize")
        return

    print(table.to_string(index=False))
    print("\nwin_rate_pct = share of trades with a positive return")
    for _, row in table.iterrows():
        label = "Realized gains" if row["state"] == "Realized" else "Unrealized gains"
        print(
            f"- {label}: [{_bar(row['win_rate_pct'])}] "
            f"{row['win_rate_pct']:.1f}% profitable, "
            f"mean {row['mean_return_pct']:+.1f}%, "
            f"median {row['median_return_pct']:+.1f}%"
        )


def _allocation_targets(
    metrics: pd.DataFrame, prices: pd.DatetimeIndex
) -> pd.Series:
    """Target allocation (0-1) for each price date, using the prior score.

    The previous day's score sets today's target, so the rebalance never peeks
    at the close it executes on. Dates before the first score stay ``NaN``
    (no signal, stay in cash).
    """
    frame = metrics[["date", "total_score"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date", "total_score"])
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    scores = frame.set_index("date")["total_score"].astype(float)
    aligned = scores.reindex(prices, method="ffill").shift(1)
    return aligned.apply(
        lambda value: allocation_ratio(value) if pd.notna(value) else np.nan
    )


def capital_performance_table(
    metrics: pd.DataFrame,
    klines: pd.DataFrame,
    initial_capital: float = INITIAL_CAPITAL,
) -> pd.DataFrame:
    """Daily rebalancing to the score-derived target allocation.

    Instead of buying/selling the whole position at zone changes, the target
    share of capital (0% at score 30, 100% at score 70, linear in between) is
    rebalanced every day using the previous day's score: the difference is
    bought when the target rises and sold when it falls. The compounded result
    is compared against buy & hold from the same start date.
    """
    if metrics.empty or klines.empty:
        return pd.DataFrame()
    if not {"date", "total_score"}.issubset(metrics.columns):
        return pd.DataFrame()

    close = klines["close"].astype(float).dropna().sort_index()
    scores = pd.to_datetime(
        metrics["date"], errors="coerce"
    ).dropna()
    if close.empty or scores.empty:
        return pd.DataFrame()

    start = scores.min()
    prices = close[close.index >= start]
    if prices.empty:
        return pd.DataFrame()

    targets = _allocation_targets(metrics, prices.index)
    if targets.dropna().empty:
        return pd.DataFrame()

    cash = initial_capital
    units = 0.0
    buy_days = 0
    sell_days = 0
    investments = []
    allocations = []
    equity = []
    for date, price in prices.items():
        price = float(price)
        target = targets.loc[date]
        equity_value = cash + units * price
        if pd.notna(target):
            desired = float(target) * equity_value
            current = units * price
            trade = desired - current
            if trade > 1e-9 and cash > 0:
                buy = min(trade, cash)
                units += buy / price
                cash -= buy
                buy_days += 1
            elif trade < -1e-9 and units > 0:
                sell = min(-trade, current)
                units -= sell / price
                cash += sell
                sell_days += 1
            allocations.append(float(target) * 100)
        equity_value = cash + units * price
        equity.append(equity_value)
        investments.append((units * price / equity_value) if equity_value else 0.0)

    equity_series = pd.Series(equity, index=prices.index, dtype=float)
    final_capital = float(equity_series.iloc[-1])
    total_return = (final_capital / initial_capital - 1) * 100
    max_drawdown = float((equity_series / equity_series.cummax() - 1).min() * 100)
    days = max((prices.index[-1] - prices.index[0]).days, 1)
    cagr = ((final_capital / initial_capital) ** (365 / days) - 1) * 100
    exposure = float(np.mean(investments)) * 100 if investments else 0.0
    avg_allocation = float(np.mean(allocations)) if allocations else np.nan

    buy_hold_units = initial_capital / float(prices.iloc[0])
    buy_hold_equity = buy_hold_units * prices
    buy_hold_final = float(buy_hold_equity.iloc[-1])
    buy_hold_return = (buy_hold_final / initial_capital - 1) * 100
    buy_hold_drawdown = float(
        (buy_hold_equity / buy_hold_equity.cummax() - 1).min() * 100
    )
    buy_hold_cagr = (
        (buy_hold_final / initial_capital) ** (365 / days) - 1
    ) * 100

    return pd.DataFrame(
        [
            {
                "strategy": "Score-scaled allocation",
                "final_capital": round(final_capital, 0),
                "profit": round(final_capital - initial_capital, 0),
                "total_return_pct": round(total_return, 1),
                "cagr_pct": round(cagr, 1),
                "max_drawdown_pct": round(max_drawdown, 1),
                "exposure_pct": round(exposure, 1),
                "avg_allocation_pct": (
                    round(avg_allocation, 1) if not np.isnan(avg_allocation) else np.nan
                ),
                "buy_days": buy_days,
                "sell_days": sell_days,
                "rebalances": buy_days + sell_days,
            },
            {
                "strategy": "Buy & hold",
                "final_capital": round(buy_hold_final, 0),
                "profit": round(buy_hold_final - initial_capital, 0),
                "total_return_pct": round(buy_hold_return, 1),
                "cagr_pct": round(buy_hold_cagr, 1),
                "max_drawdown_pct": round(buy_hold_drawdown, 1),
                "exposure_pct": 100.0,
                "avg_allocation_pct": 100.0,
                "buy_days": 1,
                "sell_days": 0,
                "rebalances": 1,
            },
        ]
    )


def capital_validation(
    metrics: pd.DataFrame, klines: pd.DataFrame
) -> None:
    """Print the compounded capital result against buy and hold."""
    print("\n=== Capital performance: score-scaled allocation vs buy & hold ===")
    print(
        f"Initial capital: ${INITIAL_CAPITAL:,.0f}. The target share of capital "
        "is 0% at score 30, 100% at score 70 (linear in between); the position "
        "is rebalanced daily to the previous day's target."
    )
    table = capital_performance_table(metrics, klines)
    if table.empty:
        print("Not enough cycle history for a capital comparison")
        return

    print(table.to_string(index=False))
    for _, row in table.iterrows():
        profit = float(row["profit"])
        profit_text = f"+${profit:,.0f}" if profit >= 0 else f"-${abs(profit):,.0f}"
        print(
            f"- {row['strategy']}: ${row['final_capital']:,.0f} final, "
            f"{profit_text} profit, "
            f"{row['total_return_pct']:+.1f}% total, "
            f"{row['cagr_pct']:.1f}% CAGR, "
            f"{row['max_drawdown_pct']:.1f}% max drawdown"
        )


def independent_table(
    metrics: pd.DataFrame,
    klines: pd.DataFrame,
    n_resamples: int = 2000,
    horizons: tuple[int, ...] = INDEPENDENT_HORIZONS,
) -> pd.DataFrame:
    """Per-zone stats on non-overlapping, bootstrapped samples.

    Daily scores overlap heavily (3312 days are ~37 independent 90d cycles),
    so this re-samples each zone at `horizon`-day spacing and wraps
    mean/win-rate in a 95% percentile-bootstrap interval.

    :return: DataFrame with zone, horizon, n and bootstrapped mean/win-rate
    """
    rows = []
    for zone, group in metrics.groupby("zone", sort=False):
        dates = pd.DatetimeIndex(group["date"])
        for horizon in horizons:
            indep = sample_independent(dates, horizon)
            returns = forward_return(klines, indep, horizon).dropna()
            if returns.empty:
                continue
            mean_lo, mean_hi = bootstrap_ci(returns, np.mean, n_resamples)
            win_lo, win_hi = bootstrap_ci(
                returns, lambda x: float((x > 0).mean()) * 100, n_resamples
            )
            rows.append(
                {
                    "zone": zone,
                    "horizon": f"{horizon}d",
                    "n": len(returns),
                    "mean_ret": f"{returns.mean():.1f}% [{mean_lo:.1f}, {mean_hi:.1f}]",
                    "win_rate": (
                        f"{float((returns > 0).mean()) * 100:.1f}%"
                        f" [{win_lo:.1f}, {win_hi:.1f}]"
                    ),
                }
            )
    return _zone_order(pd.DataFrame(rows))


def independent_validation(
    metrics: pd.DataFrame,
    klines: pd.DataFrame,
    n_resamples: int = 2000,
    horizons: tuple[int, ...] = INDEPENDENT_HORIZONS,
) -> None:
    """Report non-overlapping, bootstrapped stats for every zone."""
    print(f"\n=== Independent-sample validation (bootstrap 95% CI, {n_resamples} resamples) ===")
    print("Non-overlapping picks; wide CIs on thin zones are the honest picture.")

    table = independent_table(
        metrics, klines, n_resamples=n_resamples, horizons=horizons
    )
    if not table.empty:
        print(table.to_string(index=False))


def episode_stats_table(
    metrics: pd.DataFrame,
    klines: pd.DataFrame,
    n_resamples: int = 2000,
    horizons: tuple[int, ...] = INDEPENDENT_HORIZONS,
) -> pd.DataFrame:
    """Per-zone stats using one observation per consecutive-day run."""
    stats_rows = []
    for zone, group in metrics.groupby("zone", sort=False):
        dates = _episode_first_dates(group)
        for horizon in horizons:
            returns = forward_return(klines, dates, horizon).dropna()
            if returns.empty:
                continue
            mean_lo, mean_hi = bootstrap_ci(returns, np.mean, n_resamples)
            win_lo, win_hi = bootstrap_ci(
                returns, lambda x: float((x > 0).mean()) * 100, n_resamples
            )
            stats_rows.append(
                {
                    "zone": zone,
                    "horizon": f"{horizon}d",
                    "ep": len(returns),
                    "mean_ret": f"{returns.mean():.1f}% [{mean_lo:.1f}, {mean_hi:.1f}]",
                    "win_rate": (
                        f"{float((returns > 0).mean()) * 100:.1f}%"
                        f" [{win_lo:.1f}, {win_hi:.1f}]"
                    ),
                }
            )
    return _zone_order(pd.DataFrame(stats_rows))


def episode_evidence_table(
    metrics: pd.DataFrame,
    klines: pd.DataFrame,
    n_resamples: int = 2000,
    horizons: tuple[int, ...] = INDEPENDENT_HORIZONS,
) -> pd.DataFrame:
    """Per-zone significance of a negative edge, one observation per run.

    Combines a 95% bootstrap interval, an exact one-sided binomial test
    (H0: win rate >= 50%) and a Bayesian posterior P(win rate < 50%), which
    stays interpretable on the thin Selling-zone sample.

    :return: DataFrame with zone, horizon, episodes, wins, exact_p,
        P_mean_neg and P_win_neg
    """
    rows = []
    for zone, group in metrics.groupby("zone", sort=False):
        dates = _episode_first_dates(group)
        for horizon in horizons:
            returns = forward_return(klines, dates, horizon).dropna()
            if returns.empty:
                continue
            n = int(len(returns))
            wins = int((returns > 0).sum())
            rows.append(
                {
                    "zone": zone,
                    "horizon": f"{horizon}d",
                    "ep": n,
                    "wins": f"{wins}/{n}",
                    "exact_p": f"{_binomial_cdf(wins, n):.3f}",
                    "P_mean_neg": f"{_probability_mean_negative(returns, n_resamples):.0%}",
                    "P_win_neg": f"{1 - _binomial_cdf(wins, n + 1):.0%}",
                }
            )
    return _zone_order(pd.DataFrame(rows))


def episode_drawdown_table(
    metrics: pd.DataFrame,
    klines: pd.DataFrame,
    n_resamples: int = 2000,
    horizons: tuple[int, ...] = ALL_DRAWDOWN_HORIZONS,
) -> pd.DataFrame:
    """Per-zone forward max drawdown, one observation per run."""
    rows = []
    for zone, group in metrics.groupby("zone", sort=False):
        dates = _episode_first_dates(group)
        for horizon in horizons:
            drawdowns = forward_max_drawdown(klines, dates, horizon).dropna()
            if drawdowns.empty:
                continue
            dd_lo, dd_hi = bootstrap_ci(drawdowns, np.mean, n_resamples)
            rows.append(
                {
                    "zone": zone,
                    "horizon": f"{horizon}d",
                    "ep": len(drawdowns),
                    "mean_dd": f"{drawdowns.mean():.1f}% [{dd_lo:.1f}, {dd_hi:.1f}]",
                    "worst_dd": f"{drawdowns.min():.1f}%",
                }
            )
    return _zone_order(pd.DataFrame(rows))


def episode_validation(
    metrics: pd.DataFrame,
    klines: pd.DataFrame,
    n_resamples: int = 2000,
    horizons: tuple[int, ...] = INDEPENDENT_HORIZONS,
) -> None:
    """Validate each zone on one return per consecutive-day run.

    Daily scores conflate days with episodes (109 negative days are only 23
    runs), so this section uses one observation per run. Besides bootstrap
    CIs it reports an exact one-sided binomial test (H0: win rate >= 50%,
    i.e. no negative edge) and a Bayesian posterior probability that the
    true win rate is below 50%, which stays interpretable on tiny samples.
    """
    print("\n=== Episode-level validation (1 return per run) ===")
    print("Each consecutive-day run counts once, not each day.")

    stats_df = episode_stats_table(
        metrics, klines, n_resamples=n_resamples, horizons=horizons
    )
    if not stats_df.empty:
        print("\n--- Stats per episode ---")
        print(stats_df.to_string(index=False))

    evidence_df = episode_evidence_table(
        metrics, klines, n_resamples=n_resamples, horizons=horizons
    )
    if not evidence_df.empty:
        print("\n--- Evidence (small p_exact supports a negative edge) ---")
        print("exact_p: one-sided binomial test, H0 win rate >= 50%")
        print("P_mean_neg: bootstrap probability that episode mean return < 0")
        print("P_win_neg: Bayesian P(true win rate < 50%), Beta(1+w, 1+l)")
        print(evidence_df.to_string(index=False))

        neg = evidence_df[evidence_df["zone"] == "Selling zone"]
        if not neg.empty:
            print("\nBest-supported negative signal (Selling zone, by P_mean_neg):")
            best = neg.loc[(
                neg["P_mean_neg"].replace("%", "", regex=True).astype(float).idxmax()
            )]
            print(
                f"- {best['horizon']}: {best['wins']} winning episodes, "
                f"P(mean<0)={best['P_mean_neg']}, exact p={best['exact_p']} "
                f"(H0 win>=50%), Bayesian P(win<50%)={best['P_win_neg']}"
            )

    dd_df = episode_drawdown_table(
        metrics,
        klines,
        n_resamples=n_resamples,
        horizons=tuple(h for h in ALL_DRAWDOWN_HORIZONS if h in horizons),
    )
    if not dd_df.empty:
        print("\n--- Max drawdown per episode (worst peak-to-trough in-window) ---")
        print("mean_dd: average worst decline from a peak inside the window")
        print(dd_df.to_string(index=False))


def cycle_validation(
    metrics: pd.DataFrame, split: str = CYCLE_SPLIT
) -> None:
    """Report the long-cycle evidence separately from the 90d timing view.

    The score was designed to time accumulation across a cycle, so 365/730d
    outcomes matter more than 30/90d. This section also checks temporal
    stability and a monthly DCA overlay that uses the previous day's score.
    """
    print("\n=== Cycle-level validation (365/730d) ===")
    print(
        "The score is a long-cycle accumulation anchor, not a 30/90d timer. "
        "Correlation should improve as the horizon lengthens."
    )

    cycle_summary = summarize(metrics, CYCLE_HORIZONS)
    if cycle_summary.empty:
        print("No cycle-horizon data to summarize")
    else:
        print(cycle_summary.to_string(index=False))

    print("\n--- Score correlation by forward horizon ---")
    correlations = correlation_table(metrics, RETURN_HORIZONS)
    if correlations.empty:
        print("Not enough overlap to correlate the score")
    else:
        print(correlations.to_string(index=False))

    print(f"\n--- Temporal stability (split {split}) ---")
    stability = temporal_correlation_table(
        metrics, split=split, horizons=CYCLE_HORIZONS
    )
    if stability.empty:
        print("Not enough observations on one side of the split")
    else:
        print(stability.to_string(index=False))
        print("before_split is the design period; after_split is the stability check.")

    print("\n=== Forward max drawdown by zone (cycle windows) ===")
    cycle_dd = summarize_drawdowns(metrics, CYCLE_DRAWDOWN_HORIZONS)
    if cycle_dd.empty:
        print("No cycle-window drawdowns available")
    else:
        print(cycle_dd.to_string(index=False))

    print("\n=== Monthly DCA: flat vs score-scaled (0.5x-1.5x) ===")
    dca = monthly_dca_table(metrics)
    if dca.empty:
        print("Not enough monthly history for a DCA comparison")
    else:
        print(dca.to_string(index=False))
        print(
            "cost_improvement_pct > 0 means the score-scaled DCA bought at a "
            "lower average cost than flat DCA over the same months."
        )


def load_metrics_with_forwards(db: DatabaseManager) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load stored scores joined with their forward returns and drawdowns.

    Zones are inferred from ``total_score`` when the stored ``zone`` column is
    missing, so the frame is always usable for the summaries.

    :return: tuple of (metrics frame with ret_/dd_ columns, klines indexed by
        date), or two empty frames when the required tables are missing
    """
    empty = pd.DataFrame()
    metrics = db.load_metrics_history()
    if metrics.empty:
        logger.error("No scored metrics found; run the score backfill first")
        return empty, empty

    metrics["date"] = pd.to_datetime(metrics["date"])
    if "zone" not in metrics.columns or metrics["zone"].isna().all():
        metrics["zone"] = _bucket(
            pd.to_numeric(metrics["total_score"], errors="coerce")
        )
        logger.info("No zone stored; inferred zones from total_score")

    klines = _load_klines(db)
    if klines.empty:
        logger.error("No BTC klines found; run the BTC backfill first")
        return empty, empty

    dates = pd.DatetimeIndex(metrics["date"])
    for horizon in RETURN_HORIZONS:
        metrics[f"ret_{horizon}d"] = forward_return(klines, dates, horizon).to_numpy()
    for horizon in ALL_DRAWDOWN_HORIZONS:
        metrics[f"dd_{horizon}d"] = forward_max_drawdown(klines, dates, horizon).to_numpy()

    return metrics, klines


def run_backtest(
    csv_path: str | None = None,
    independent: bool = False,
    resamples: int = 2000,
    split: str = CYCLE_SPLIT,
    long_term: bool = False,
) -> pd.DataFrame:
    db = DatabaseManager()
    metrics, klines = load_metrics_with_forwards(db)
    if metrics.empty or klines.empty:
        return pd.DataFrame()

    if long_term:
        result = summarize(metrics, CYCLE_HORIZONS)
    else:
        result = summarize(metrics)
        dd_summary = summarize_drawdowns(metrics)

        print("\n=== Forward returns by score zone ===")
        if result.empty:
            print("No data to summarize")
        else:
            print(result.to_string(index=False))
            print("\nInterpretation:")
            for _, row in result.iterrows():
                print(
                    f"- {row['zone']} (n={int(row['n'])}): "
                    f"mean 90d={row.get('mean_90d')}% "
                    f"(win rate {row.get('win_rate_90d')}%)"
                )

        corr = metrics.dropna(subset=["total_score", "ret_90d"])
        if len(corr) >= 10:
            correlation = corr["total_score"].corr(corr["ret_90d"])
            print(f"\nCorrelation score vs 90d forward return: {correlation:.3f}")

        print("\n=== Forward max drawdown by zone (worst peak-to-trough in-window) ===")
        if dd_summary.empty:
            print("No data to summarize")
        else:
            print(dd_summary.to_string(index=False))
            print("\nReturns measure the end-line; drawdown measures the journey:")
            neg_zone = dd_summary[dd_summary["zone"] == "Selling zone"]
            high_zone = dd_summary[dd_summary["zone"] == "High accumulation zone"]
            for horizon in DRAWDOWN_HORIZONS:
                if neg_zone.empty or high_zone.empty:
                    continue
                col = f"mean_dd_{horizon}d"
                n_mean = float(neg_zone[col].iloc[0])
                h_mean = float(high_zone[col].iloc[0])
                print(
                    f"- At {horizon}d the Selling zone averages {n_mean:.1f}% vs "
                    f"{h_mean:.1f}% for High accumulation (more negative = deeper "
                    f"decline)."
                )

    cycle_validation(metrics, split=split)

    if independent:
        horizons = CYCLE_HORIZONS if long_term else INDEPENDENT_HORIZONS
        independent_validation(
            metrics, klines, n_resamples=resamples, horizons=horizons
        )
        episode_validation(
            metrics, klines, n_resamples=resamples, horizons=horizons
        )

    playbook_validation(metrics, klines)
    capital_validation(metrics, klines)

    if csv_path:
        metrics.to_csv(csv_path, index=False)
        logger.info(f"Backtest details saved to {csv_path}")

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the accumulation score with forward returns"
    )
    parser.add_argument(
        "--csv", help="Optional CSV path to store the per-day details"
    )
    parser.add_argument(
        "--independent",
        action="store_true",
        help="Also run the non-overlapping bootstrap validation",
    )
    parser.add_argument(
        "--resamples",
        type=int,
        default=2000,
        help="Bootstrap resamples for the independent validation (default 2000)",
    )
    parser.add_argument(
        "--split",
        default=CYCLE_SPLIT,
        help="Temporal stability split date (default 2022-01-01)",
    )
    parser.add_argument(
        "--long-term",
        dest="long_term",
        action="store_true",
        help="Only run the 365/730d cycle validation",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_backtest(
        csv_path=args.csv,
        independent=args.independent,
        resamples=args.resamples,
        split=args.split,
        long_term=args.long_term,
    )


if __name__ == "__main__":
    main()