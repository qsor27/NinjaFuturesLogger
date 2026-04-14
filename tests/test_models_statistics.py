from datetime import date

import pytest
from pydantic import ValidationError

from models.statistics import (
    DistributionResponse,
    EquityCurveResponse,
    EquityPoint,
    EquitySeries,
    HistogramBucket,
    HourBucket,
    HourBucketResponse,
    InstrumentBreakdown,
    InstrumentStats,
    SideBreakdown,
    SideStats,
    StatsFilter,
    StatsSummary,
    TimeBucket,
    TimeBucketResponse,
)


def test_stats_filter_defaults_all_none():
    f = StatsFilter()
    assert f.account is None
    assert f.from_date is None
    assert f.to_date is None


def test_stats_filter_accepts_dates():
    f = StatsFilter(account="Sim", from_date=date(2026, 1, 1), to_date=date(2026, 4, 13))
    assert f.from_date == date(2026, 1, 1)


def test_stats_summary_minimum_fields():
    s = StatsSummary(
        total_positions=0,
        total_pnl=0.0,
        wins=0,
        losses=0,
        scratches=0,
        win_rate=None,
        avg_win=None,
        avg_loss=None,
        profit_factor=None,
        largest_win=None,
        largest_loss=None,
        longest_win_streak=0,
        longest_loss_streak=0,
        avg_hold_minutes=None,
        median_hold_minutes=None,
        avg_position_size=None,
        open_positions=0,
        skipped_no_multiplier=0,
    )
    assert s.total_positions == 0


def test_stats_summary_rejects_extra_field():
    with pytest.raises(ValidationError):
        StatsSummary(
            total_positions=0,
            total_pnl=0.0,
            wins=0,
            losses=0,
            scratches=0,
            win_rate=None,
            avg_win=None,
            avg_loss=None,
            profit_factor=None,
            largest_win=None,
            largest_loss=None,
            longest_win_streak=0,
            longest_loss_streak=0,
            avg_hold_minutes=None,
            median_hold_minutes=None,
            avg_position_size=None,
            open_positions=0,
            skipped_no_multiplier=0,
            extra_field="boom",
        )


def test_instrument_breakdown_round_trip():
    payload = InstrumentBreakdown(
        rows=[
            InstrumentStats(
                instrument="MNQ",
                position_count=2,
                total_pnl=120.0,
                win_rate=0.5,
                avg_pnl_per_position=60.0,
            )
        ]
    )
    assert payload.rows[0].instrument == "MNQ"


def test_time_bucket_response_holds_granularity():
    payload = TimeBucketResponse(
        granularity="day",
        buckets=[TimeBucket(bucket="2026-04-13", position_count=1, total_pnl=10.0)],
    )
    assert payload.granularity == "day"
    assert payload.buckets[0].bucket == "2026-04-13"


def test_hour_bucket_response_carries_timezone():
    payload = HourBucketResponse(
        timezone="America/Chicago",
        buckets=[HourBucket(hour=h, position_count=0, total_pnl=0.0) for h in range(24)],
    )
    assert len(payload.buckets) == 24
    assert payload.buckets[0].hour == 0
    assert payload.buckets[23].hour == 23


def test_side_breakdown():
    payload = SideBreakdown(
        long=SideStats(position_count=3, total_pnl=10.0, win_rate=1.0),
        short=SideStats(position_count=2, total_pnl=-5.0, win_rate=0.0),
    )
    assert payload.long.position_count == 3


def test_equity_curve_response_series():
    payload = EquityCurveResponse(
        series=[
            EquitySeries(
                account="Sim",
                points=[
                    EquityPoint(time="2026-04-07", cumulative_pnl=10.0),
                    EquityPoint(time="2026-04-08", cumulative_pnl=15.0),
                ],
            )
        ]
    )
    assert len(payload.series) == 1
    assert payload.series[0].account == "Sim"
    assert payload.series[0].points[1].time == "2026-04-08"


def test_equity_curve_response_multi_series():
    payload = EquityCurveResponse(
        series=[
            EquitySeries(account="A", points=[EquityPoint(time="2026-04-07", cumulative_pnl=5.0)]),
            EquitySeries(account="B", points=[EquityPoint(time="2026-04-07", cumulative_pnl=-3.0)]),
        ]
    )
    assert [s.account for s in payload.series] == ["A", "B"]


def test_distribution_response():
    payload = DistributionResponse(
        buckets=[HistogramBucket(bucket_min=-100.0, bucket_max=-90.0, count=1)],
        bucket_count=10,
    )
    assert payload.bucket_count == 10
