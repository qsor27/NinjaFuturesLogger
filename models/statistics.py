from datetime import date
from typing import Literal

from models.base import StrictModel


class StatsFilter(StrictModel):
    account: str | None = None
    from_date: date | None = None  # inclusive, session date
    to_date: date | None = None  # inclusive, session date
    side: Literal["Long", "Short"] | None = None


class StatsSummary(StrictModel):
    total_positions: int
    total_pnl: float
    wins: int
    losses: int
    scratches: int
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    profit_factor: float | None
    largest_win: float | None
    largest_loss: float | None
    longest_win_streak: int
    longest_loss_streak: int
    avg_hold_minutes: float | None
    median_hold_minutes: float | None
    avg_position_size: float | None
    open_positions: int
    skipped_no_multiplier: int


class InstrumentStats(StrictModel):
    instrument: str
    position_count: int
    total_pnl: float
    win_rate: float | None
    avg_pnl_per_position: float


class InstrumentBreakdown(StrictModel):
    rows: list[InstrumentStats]


class TimeBucket(StrictModel):
    bucket: str  # "2026-04-13" / "2026-W15" / "2026-04"
    position_count: int
    total_pnl: float


class TimeBucketResponse(StrictModel):
    granularity: Literal["day", "week", "month"]
    buckets: list[TimeBucket]


class HourBucket(StrictModel):
    hour: int  # 0..23 in display_timezone
    position_count: int
    total_pnl: float
    win_rate: float | None = None  # wins / (wins + losses) among trades in this hour


class HourBucketResponse(StrictModel):
    timezone: str  # IANA name, e.g. "America/Chicago"
    buckets: list[HourBucket]


class SideStats(StrictModel):
    position_count: int
    total_pnl: float
    win_rate: float | None
    avg_win: float | None = None
    avg_loss: float | None = None
    profit_factor: float | None = None


class SideBreakdown(StrictModel):
    long: SideStats
    short: SideStats


class EquityPoint(StrictModel):
    time: str  # ISO date YYYY-MM-DD, one point per session date
    cumulative_pnl: float


class EquitySeries(StrictModel):
    account: str
    points: list[EquityPoint]


class EquityCurveResponse(StrictModel):
    series: list[EquitySeries]


class HistogramBucket(StrictModel):
    bucket_min: float
    bucket_max: float
    count: int


class DistributionResponse(StrictModel):
    buckets: list[HistogramBucket]
    bucket_count: int


class DayOfWeekBucket(StrictModel):
    dow: int           # 0=Mon … 4=Fri
    day_name: str      # "Mon" … "Fri"
    trading_days: int  # unique session dates for this weekday
    trades: int
    avg_pnl: float     # total_pnl / trading_days, 0.0 when trading_days == 0
    win_rate: float | None
    total_pnl: float


class DayOfWeekResponse(StrictModel):
    buckets: list[DayOfWeekBucket]  # always 5 rows, Mon–Fri order


class TradesPerDayBucket(StrictModel):
    trades_per_day: int       # bucket key
    days: int                 # unique session dates with this trade count
    total_trades: int         # trades_per_day * days
    wins: int
    losses: int
    total_pnl: float          # sum across those days
    avg_pnl: float            # total_pnl / days
    win_rate: float | None    # per-trade win rate on those days


class TradesPerDayResponse(StrictModel):
    buckets: list[TradesPerDayBucket]
