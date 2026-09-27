"""Pydantic response models for the documented endpoints.

Endpoints that return wide, column-per-horizon tables (backtest summaries)
deliberately use plain dicts so new horizons do not require a schema change;
they are described in the route docstrings instead.
"""

from typing import Any

from pydantic import BaseModel, Field


class ReportComponents(BaseModel):
    """Per-signal sub-scores, 0-100 (higher = more attractive to accumulate)."""

    google_trends: float
    macd: float
    dxy: float
    m2: float
    ema_200: float
    fear_greed: float
    rsi: float


class ZoneHistory(BaseModel):
    """Forward performance of the current zone over the stored history."""

    n: int
    mean: float = Field(description="Mean forward return in %")
    win: float = Field(description="Share of positive forward returns in %")


class BtcReport(BaseModel):
    """The report of one day, as shown on the dashboard."""

    date: str = Field(description="Report date, YYYY-MM-DD")
    btc_price: float
    ema_200: float
    rsi_14: float
    fear_greed: int
    m2_yoy: float = Field(description="M2 money supply year-over-year growth in %")
    sp500: float | None = None
    nasdaq: float | None = None
    dxy: str = Field(description="DXY short-term trend: bullish | bearish | neutral")
    macd_hist: float
    google_trends: float
    total_score: int = Field(ge=0, le=100)
    zone: str
    components: ReportComponents
    zone_history: ZoneHistory | None = Field(
        default=None,
        description="Historical 90d stats for the current zone, when stored",
    )


class ScoreSnapshot(BtcReport):
    """`BtcReport` plus the buy action and where the numbers came from."""

    action: str = Field(description="Recommended action for the current zone")
    ratio: float = Field(ge=0, le=1, description="Share of the monthly budget to deploy")
    source: str = Field(description="'stored' (last pipeline run) or 'live' (just fetched)")
    latest_candle_date: str | None = None
    fallbacks: dict[str, Any] | None = None


class ComponentMeta(BaseModel):
    """Static semantics of one score component, for building the UI."""

    key: str
    weight: float
    tag: str
    description: str
    contrarian: bool


class ScoreTrend(BaseModel):
    """How the total score moved recently, in score points."""

    current: int | None = None
    change_7d: int | None = None
    change_30d: int | None = None
    min_90d: int | None = None
    max_90d: int | None = None


class ZoneAbove(BaseModel):
    """The better zone right above the current score."""

    zone: str
    min_score: float = Field(description="Score that opens the zone")
    points_needed: float = Field(description="Score points still missing to move up")


class ZoneBelow(BaseModel):
    """The worse zone right below the current score."""

    zone: str
    below_score: float = Field(description="Score below which the zone takes over")
    headroom: float = Field(description="Score points above that boundary")


class ZoneThresholds(BaseModel):
    """The two zone boundaries around the current score."""

    score: int | None = None
    zone: str
    up: ZoneAbove | None = Field(default=None, description="Better zone above")
    down: ZoneBelow | None = Field(default=None, description="Worse zone below")


class ZoneRun(BaseModel):
    """A stretch of consecutive days spent in the same zone."""

    zone: str
    start: str | None = None
    end: str | None = None
    days: int
    score: int | None = None


class ZoneTransition(BaseModel):
    """One zone change, with the direction of the move."""

    date: str | None = None
    from_zone: str
    to_zone: str
    direction: str = Field(description="'up' towards a better zone, 'down' otherwise")
    days_in_previous: int
    previous_end: str | None = None


class ZoneDistribution(BaseModel):
    """How much of the stored history each zone occupies."""

    zone: str
    days: int
    share_pct: float
    episodes: int = Field(description="Consecutive runs of that zone")
    mean_episode_days: float | None = None
    median_episode_days: float | None = None
    first_seen: str | None = None
    last_seen: str | None = None


class PriceContext(BaseModel):
    """Where the last stored price sits in its own cycle."""

    price: float
    as_of: str | None = None
    vs_ema_200_pct: float | None = None
    ath: float
    ath_date: str | None = None
    drawdown_from_ath_pct: float | None = None
    percentile_365d: float | None = Field(
        default=None, description="Percentile of the last price within its year"
    )
    change_7d_pct: float | None = None
    change_30d_pct: float | None = None
    change_90d_pct: float | None = None


class CurrentZone(BaseModel):
    """The zone the market is in right now, and for how long."""

    date: str | None = None
    zone: str
    score: int | None = None
    action: str
    ratio: float = Field(ge=0, le=1, description="Share of the monthly budget to deploy")
    streak_days: int = Field(description="Consecutive stored days in this zone")
    streak_start: str | None = None
    zone_history: ZoneHistory | None = Field(
        default=None, description="Historical 90d stats for this zone"
    )
    score_trend: ScoreTrend


class ZoneSample(BaseModel):
    """Stored history the zone context was computed from."""

    start: str | None = None
    end: str | None = None
    days: int
    episodes: int


class ZoneContextResponse(BaseModel):
    """Where the market sits inside its zone, as embedded in the dashboard."""

    current: CurrentZone
    previous: ZoneRun | None = None
    thresholds: ZoneThresholds
    price_context: PriceContext | None = Field(
        default=None, description="Null when no candles are stored yet"
    )
    distribution: list[ZoneDistribution]
    transitions: list[ZoneTransition]
    sample: ZoneSample


class ModelConfigResponse(BaseModel):
    """Weights, zone thresholds and buy actions of the scoring model."""

    weights: dict[str, float]
    zones: list[dict[str, Any]]
    actions: dict[str, dict[str, Any]]
    components: list[ComponentMeta]


class HealthResponse(BaseModel):
    """Service and database status."""

    status: str
    database: str
    db_path: str
    tables: dict[str, int]
    latest_score_date: str | None = None
    latest_score: int | None = None
    server_time: str


class CalibrationQuartile(BaseModel):
    """Mean forward return within one quartile of a component's sub-score."""

    quartile: int = Field(ge=1, le=4, description="1 = lowest sub-scores")
    n: int
    mean: float = Field(description="Mean forward return in %")


class CalibrationComponent(BaseModel):
    """How predictive one component's sub-score is, next to its live weight."""

    key: str
    weight: float = Field(description="Weight in the composite score")
    pearson: float | None = Field(
        default=None, description="Correlation with the forward return, or None"
    )
    verdict: str = Field(description="positive | negative | noise | no_data")
    tag: str | None = None
    description: str | None = None
    contrarian: bool | None = None
    quartiles: list[CalibrationQuartile] = Field(
        default_factory=list, description="Mean return per sub-score quartile"
    )


class CalibrationScoreBin(BaseModel):
    """The composite score bucketed in bands of 10 points."""

    bin: str
    n: int
    mean: float
    median: float
    win_rate: float


class CalibrationResponse(BaseModel):
    """Per-component diagnostic, as embedded in the dashboard."""

    horizon_days: int
    sample: dict[str, Any]
    components: list[CalibrationComponent]
    score_bins: list[CalibrationScoreBin]
    total_score_pearson: float | None = None
    note: str | None = None


class DashboardResponse(BaseModel):
    """Contract of `GET /api/dashboard`: every first-paint section at once.

    ``report`` is a ``ScoreSnapshot``, not a bare ``BtcReport``, so the buy
    action and the ratio to deploy survive the response filter. ``backtest`` and
    ``calibration`` are the two blocks that justify the weights, kept here so a
    front page does not need extra requests to show them.
    """

    generated_at: str
    report: ScoreSnapshot | None = None
    zone: ZoneContextResponse | None = None
    macro: dict[str, Any]
    config: ModelConfigResponse
    backtest: dict[str, Any] = Field(
        description="Forward return per zone/horizon and the score correlation"
    )
    calibration: CalibrationResponse
    health: HealthResponse
    history: dict[str, Any]
