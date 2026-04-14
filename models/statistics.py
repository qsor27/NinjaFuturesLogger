from datetime import date
from typing import Literal

from models.base import StrictModel


class StatsFilter(StrictModel):
    account: str | None = None
    from_date: date | None = None  # inclusive, session date
    to_date: date | None = None  # inclusive, session date


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


class HourBucketResponse(StrictModel):
    timezone: str  # IANA name, e.g. "America/Chicago"
    buckets: list[HourBucket]


class SideStats(StrictModel):
    position_count: int
    total_pnl: float
    win_rate: float | None


class SideBreakdown(StrictModel):
    long: SideStats
    short: SideStats


class EquityPoint(StrictModel):
    time: int  # unix seconds, the position's exit_time
    cumulative_pnl: float


class EquityCurveResponse(StrictModel):
    points: list[EquityPoint]


class HistogramBucket(StrictModel):
    bucket_min: float
    bucket_max: float
    count: int


class DistributionResponse(StrictModel):
    buckets: list[HistogramBucket]
    bucket_count: int
