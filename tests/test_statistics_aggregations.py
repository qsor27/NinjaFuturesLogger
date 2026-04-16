import pytest

from models.position import Position
from services.statistics_aggregations import compute_summary


def _pos(
    *,
    eid: str = "e",
    side: str = "Long",
    entry_time: int = 100,
    exit_time: int | None = 200,
    dollars_pnl: float | None = 10.0,
    commission: float = 0.0,
    quantity: int = 1,
    duration_minutes: float | None = 1.0,
) -> Position:
    return Position(
        account="Sim",
        instrument="MNQ",
        entry_execution_id=eid,
        side=side,  # type: ignore[arg-type]
        entry_time=entry_time,
        exit_time=exit_time,
        quantity=quantity,
        entry_price=100.0,
        exit_price=101.0,
        points_pnl=1.0,
        dollars_pnl=dollars_pnl,
        commission=commission,
        duration_minutes=duration_minutes,
        execution_ids=[eid],
    )


def test_compute_summary_empty_input():
    s = compute_summary([])
    assert s.total_positions == 0
    assert s.total_pnl == 0.0
    assert s.wins == 0
    assert s.losses == 0
    assert s.scratches == 0
    assert s.win_rate is None
    assert s.avg_win is None
    assert s.avg_loss is None
    assert s.profit_factor is None
    assert s.largest_win is None
    assert s.largest_loss is None
    assert s.longest_win_streak == 0
    assert s.longest_loss_streak == 0
    assert s.avg_hold_minutes is None
    assert s.median_hold_minutes is None
    assert s.avg_position_size is None
    assert s.open_positions == 0
    assert s.skipped_no_multiplier == 0


def test_compute_summary_single_winner():
    s = compute_summary([_pos(dollars_pnl=50.0, commission=2.0)])
    assert s.total_positions == 1
    assert s.wins == 1
    assert s.losses == 0
    assert s.scratches == 0
    assert s.win_rate == 1.0
    assert s.avg_win == 50.0
    assert s.avg_loss is None
    assert s.profit_factor is None  # no losers
    assert s.largest_win == 50.0
    assert s.largest_loss is None
    assert s.longest_win_streak == 1
    assert s.longest_loss_streak == 0


def test_compute_summary_scratch_band_uses_commission():
    # |dollars_pnl| <= commission means scratch.
    s = compute_summary([_pos(dollars_pnl=2.0, commission=2.0)])
    assert s.scratches == 1
    assert s.wins == 0
    assert s.losses == 0
    assert s.win_rate is None  # 0/(0+0) = null


def test_compute_summary_mixed():
    positions = [
        _pos(eid="a", dollars_pnl=100.0, commission=2.0),  # winner
        _pos(eid="b", dollars_pnl=-50.0, commission=2.0),  # loser
        _pos(eid="c", dollars_pnl=200.0, commission=2.0),  # winner
        _pos(eid="d", dollars_pnl=-100.0, commission=2.0),  # loser
        _pos(eid="e", dollars_pnl=1.0, commission=2.0),  # scratch
    ]
    s = compute_summary(positions)
    assert s.total_positions == 5
    assert s.total_pnl == 151.0
    assert s.wins == 2
    assert s.losses == 2
    assert s.scratches == 1
    assert s.win_rate == 0.5
    assert s.avg_win == 150.0
    assert s.avg_loss == -75.0
    assert s.profit_factor == pytest.approx(2.0)  # 300 / 150
    assert s.largest_win == 200.0
    assert s.largest_loss == -100.0


def test_compute_summary_streaks_alternating():
    # W L W L W -> longest win streak 1, longest loss streak 1
    positions = [
        _pos(eid="1", dollars_pnl=10.0, commission=0.0, exit_time=10),
        _pos(eid="2", dollars_pnl=-10.0, commission=0.0, exit_time=20),
        _pos(eid="3", dollars_pnl=10.0, commission=0.0, exit_time=30),
        _pos(eid="4", dollars_pnl=-10.0, commission=0.0, exit_time=40),
        _pos(eid="5", dollars_pnl=10.0, commission=0.0, exit_time=50),
    ]
    s = compute_summary(positions)
    assert s.longest_win_streak == 1
    assert s.longest_loss_streak == 1


def test_compute_summary_streaks_runs():
    # W W W L L W L L L W -> longest win 3, longest loss 3
    pnls = [10, 10, 10, -10, -10, 10, -10, -10, -10, 10]
    positions = [
        _pos(eid=str(i), dollars_pnl=float(p), commission=0.0, exit_time=10 * (i + 1))
        for i, p in enumerate(pnls)
    ]
    s = compute_summary(positions)
    assert s.longest_win_streak == 3
    assert s.longest_loss_streak == 3


def test_compute_summary_streaks_skip_scratches():
    # Scratches break neither streak.
    positions = [
        _pos(eid="1", dollars_pnl=10.0, commission=0.0, exit_time=10),
        _pos(eid="2", dollars_pnl=10.0, commission=0.0, exit_time=20),
        _pos(eid="3", dollars_pnl=0.0, commission=0.0, exit_time=30),  # scratch
        _pos(eid="4", dollars_pnl=10.0, commission=0.0, exit_time=40),
    ]
    s = compute_summary(positions)
    assert s.longest_win_streak == 3


def test_compute_summary_streaks_ordered_by_exit_time():
    # Out-of-order input; helper sorts by exit_time before walking.
    positions = [
        _pos(eid="3", dollars_pnl=-10.0, commission=0.0, exit_time=30),
        _pos(eid="1", dollars_pnl=10.0, commission=0.0, exit_time=10),
        _pos(eid="2", dollars_pnl=10.0, commission=0.0, exit_time=20),
    ]
    s = compute_summary(positions)
    assert s.longest_win_streak == 2
    assert s.longest_loss_streak == 1


def test_compute_summary_hold_time_median_odd_and_even():
    odd = [
        _pos(eid="1", duration_minutes=1.0),
        _pos(eid="2", duration_minutes=3.0),
        _pos(eid="3", duration_minutes=5.0),
    ]
    even = odd + [_pos(eid="4", duration_minutes=7.0)]
    assert compute_summary(odd).median_hold_minutes == 3.0
    assert compute_summary(even).median_hold_minutes == 4.0


def test_compute_summary_avg_position_size():
    positions = [
        _pos(eid="1", quantity=2),
        _pos(eid="2", quantity=4),
    ]
    assert compute_summary(positions).avg_position_size == 3.0


from datetime import date as _date  # noqa: E402

from services.statistics_aggregations import bucket_by_session_date  # noqa: E402


def _at(unix_ts: int, *, eid: str, pnl: float = 10.0) -> Position:
    return _pos(eid=eid, entry_time=unix_ts, exit_time=unix_ts + 60, dollars_pnl=pnl)


def test_bucket_by_day_continuous_fill():
    # Three positions: two on 2026-04-13, none on 2026-04-14, one on 2026-04-15.
    # All before 16:00 Chicago time so session date == calendar date.
    # 2026-04-13 09:00 UTC = 2026-04-13 04:00 CDT
    positions = [
        _at(1776070800, eid="a", pnl=10.0),  # 2026-04-13
        _at(1776071400, eid="b", pnl=20.0),  # 2026-04-13
        _at(1776243600, eid="c", pnl=30.0),  # 2026-04-15
    ]
    result = bucket_by_session_date(positions, granularity="day")
    keys = [b.bucket for b in result]
    assert keys == ["2026-04-13", "2026-04-14", "2026-04-15"]
    assert result[0].position_count == 2
    assert result[0].total_pnl == 30.0
    assert result[1].position_count == 0
    assert result[1].total_pnl == 0.0
    assert result[2].position_count == 1
    assert result[2].total_pnl == 30.0


def test_bucket_by_day_explicit_range_pads_left_and_right():
    positions = [_at(1776070800, eid="a", pnl=10.0)]  # 2026-04-13
    result = bucket_by_session_date(
        positions,
        granularity="day",
        from_date=_date(2026, 4, 11),
        to_date=_date(2026, 4, 14),
    )
    keys = [b.bucket for b in result]
    assert keys == ["2026-04-11", "2026-04-12", "2026-04-13", "2026-04-14"]
    assert result[2].total_pnl == 10.0
    assert result[0].total_pnl == 0.0
    assert result[3].total_pnl == 0.0


def test_bucket_by_day_empty_input_with_no_range_returns_empty():
    assert bucket_by_session_date([], granularity="day") == []


def test_bucket_by_day_empty_input_with_range_zero_fills():
    result = bucket_by_session_date(
        [],
        granularity="day",
        from_date=_date(2026, 4, 13),
        to_date=_date(2026, 4, 14),
    )
    assert [b.bucket for b in result] == ["2026-04-13", "2026-04-14"]
    assert all(b.position_count == 0 and b.total_pnl == 0.0 for b in result)


def test_bucket_by_week_iso_week_keys():
    # 2026-04-13 is a Monday — ISO week 16
    positions = [_at(1776070800, eid="a", pnl=10.0)]
    result = bucket_by_session_date(positions, granularity="week")
    assert result[0].bucket == "2026-W16"


def test_bucket_by_week_continuous_two_weeks():
    positions = [
        _at(1776070800, eid="a", pnl=10.0),  # 2026-04-13 -> W16
        _at(1776675600, eid="b", pnl=20.0),  # 2026-04-20 -> W17 (Mon)
    ]
    result = bucket_by_session_date(positions, granularity="week")
    assert [b.bucket for b in result] == ["2026-W16", "2026-W17"]


def test_bucket_by_month_keys_and_continuous_fill():
    positions = [
        _at(1776070800, eid="a", pnl=10.0),  # 2026-04-13
        _at(1781341200, eid="b", pnl=20.0),  # 2026-06-13
    ]
    result = bucket_by_session_date(positions, granularity="month")
    assert [b.bucket for b in result] == ["2026-04", "2026-05", "2026-06"]
    assert result[0].total_pnl == 10.0
    assert result[1].total_pnl == 0.0
    assert result[2].total_pnl == 20.0


def test_bucket_uses_session_date_not_calendar():
    # 2026-04-13 21:30 UTC = 16:30 CDT -> rolls over to session 2026-04-14
    positions = [_at(1776115800, eid="rollover", pnl=10.0)]
    result = bucket_by_session_date(positions, granularity="day")
    assert result[0].bucket == "2026-04-14"


from zoneinfo import ZoneInfo  # noqa: E402

from services.statistics_aggregations import (  # noqa: E402
    bucket_by_hour,
    cumulative_equity,
    per_instrument,
    pnl_histogram,
    split_by_side,
)


def test_bucket_by_hour_returns_24_entries_in_chicago():
    # 2026-04-13 09:00 UTC = 04:00 America/Chicago (CDT)
    positions = [_at(1776070800, eid="a", pnl=10.0)]
    result = bucket_by_hour(positions, display_tz=ZoneInfo("America/Chicago"))
    assert len(result) == 24
    assert result[0].hour == 0
    assert result[23].hour == 23
    assert result[4].position_count == 1
    assert result[4].total_pnl == 10.0
    other_hours = [b for b in result if b.hour != 4]
    assert all(b.position_count == 0 for b in other_hours)


def test_bucket_by_hour_in_tokyo_shifts_the_bucket():
    # Same UTC moment, in Asia/Tokyo (+09:00) -> 18:00 local
    positions = [_at(1776070800, eid="a", pnl=10.0)]
    result = bucket_by_hour(positions, display_tz=ZoneInfo("Asia/Tokyo"))
    assert result[18].position_count == 1
    assert result[4].position_count == 0


def test_cumulative_equity_orders_by_exit_time():
    # Use timestamps on distinct UTC days so each position gets its own point.
    DAY1, DAY2, DAY3 = 86400, 86400 * 2, 86400 * 3  # 1970-01-02/03/04
    positions = [
        _pos(eid="b", exit_time=DAY2, dollars_pnl=5.0),
        _pos(eid="a", exit_time=DAY1, dollars_pnl=10.0),
        _pos(eid="c", exit_time=DAY3, dollars_pnl=-3.0),
    ]
    points = cumulative_equity(positions)
    assert [p.time for p in points] == ["1970-01-02", "1970-01-03", "1970-01-04"]
    assert [p.cumulative_pnl for p in points] == [10.0, 15.0, 12.0]


def test_cumulative_equity_collapses_same_day():
    # Multiple positions on the same UTC day → one point with closing cumulative.
    DAY = 86400  # 1970-01-02; use different seconds within the same day
    positions = [
        _pos(eid="a", exit_time=DAY + 100, dollars_pnl=10.0),
        _pos(eid="b", exit_time=DAY + 200, dollars_pnl=5.0),
    ]
    points = cumulative_equity(positions)
    assert len(points) == 1
    assert points[0].time == "1970-01-02"
    assert points[0].cumulative_pnl == 15.0


def test_cumulative_equity_skips_open_positions():
    positions = [
        _pos(eid="a", exit_time=None, dollars_pnl=None),
        _pos(eid="b", exit_time=86400, dollars_pnl=5.0),
    ]
    points = cumulative_equity(positions)
    assert len(points) == 1
    assert points[0].cumulative_pnl == 5.0


def test_pnl_histogram_ten_buckets():
    positions = [
        _pos(eid=str(i), dollars_pnl=float(v))
        for i, v in enumerate([-100, -80, -60, -40, -20, 0, 20, 40, 60, 100])
    ]
    h = pnl_histogram(positions)
    assert len(h) == 10
    assert h[0].bucket_min == -100.0
    assert h[-1].bucket_max == 100.0
    # All ten positions accounted for
    assert sum(b.count for b in h) == 10


def test_pnl_histogram_empty_input():
    assert pnl_histogram([]) == []


def test_pnl_histogram_single_value_collapses_to_one_loaded_bucket():
    positions = [_pos(eid="a", dollars_pnl=42.0)]
    h = pnl_histogram(positions)
    assert len(h) == 10
    assert sum(b.count for b in h) == 1


def test_split_by_side():
    longs = [_pos(eid="a", side="Long")]
    shorts = [_pos(eid="b", side="Short"), _pos(eid="c", side="Short")]
    ls, ss = split_by_side(longs + shorts)
    assert len(ls) == 1
    assert len(ss) == 2


def test_per_instrument_one_instrument():
    positions = [
        _pos(eid="a", dollars_pnl=10.0, commission=0.0),
        _pos(eid="b", dollars_pnl=20.0, commission=0.0),
    ]
    rows = per_instrument(positions)
    assert len(rows) == 1
    row = rows[0]
    assert row.instrument == "MNQ"
    assert row.position_count == 2
    assert row.total_pnl == 30.0
    assert row.win_rate == 1.0
    assert row.avg_pnl_per_position == 15.0


def test_per_instrument_groups_distinct_symbols():
    a = _pos(eid="a", dollars_pnl=10.0)
    # Construct a second position via the factory but with a different
    # instrument by re-creating the model (StrictModel — use Position(...)).
    from models.position import Position

    b = Position(
        account="Sim",
        instrument="ES",
        entry_execution_id="b",
        side="Long",
        entry_time=100,
        exit_time=200,
        quantity=1,
        entry_price=100.0,
        exit_price=101.0,
        points_pnl=1.0,
        dollars_pnl=10.0,
        commission=0.0,
        duration_minutes=1.0,
        execution_ids=["b"],
    )
    rows = per_instrument([a, b])
    instruments = sorted(r.instrument for r in rows)
    assert instruments == ["ES", "MNQ"]


from services.statistics_aggregations import bucket_by_day_of_week  # noqa: E402,I001


# Timestamps (all 09:00 UTC, before 16:00 CDT rollover, so session date == calendar date):
# 1776070800 = 2026-04-13 Mon (dow 0)  — confirmed by existing test_bucket_by_week_iso_week_keys
# 1776157200 = 2026-04-14 Tue (dow 1)
# 1776243600 = 2026-04-15 Wed (dow 2)  — confirmed by existing test_bucket_by_day_continuous_fill
# 1776330000 = 2026-04-16 Thu (dow 3)
# 1776416400 = 2026-04-17 Fri (dow 4)
# 1776675600 = 2026-04-20 Mon (dow 0)  — confirmed by existing test_bucket_by_week_continuous_two_weeks


def test_dow_always_returns_five_rows():
    result = bucket_by_day_of_week([])
    assert len(result) == 5
    assert [b.dow for b in result] == [0, 1, 2, 3, 4]
    assert [b.day_name for b in result] == ["Mon", "Tue", "Wed", "Thu", "Fri"]


def test_dow_empty_rows_zeroed():
    result = bucket_by_day_of_week([])
    assert all(b.trades == 0 for b in result)
    assert all(b.trading_days == 0 for b in result)
    assert all(b.total_pnl == 0.0 for b in result)
    assert all(b.avg_pnl == 0.0 for b in result)
    assert all(b.win_rate is None for b in result)


def test_dow_single_monday_position():
    positions = [_at(1776070800, eid="a", pnl=100.0)]
    result = bucket_by_day_of_week(positions)
    mon = result[0]
    assert mon.trades == 1
    assert mon.trading_days == 1
    assert mon.total_pnl == 100.0
    assert mon.avg_pnl == 100.0
    # Other days untouched
    assert all(b.trades == 0 for b in result[1:])


def test_dow_win_rate_and_avg_pnl_across_two_mondays():
    # Two Monday sessions: +100 and -50 → win_rate 0.5, avg_pnl 25.0
    positions = [
        _at(1776070800, eid="a", pnl=100.0),   # 2026-04-13 Mon
        _at(1776675600, eid="b", pnl=-50.0),   # 2026-04-20 Mon
    ]
    result = bucket_by_day_of_week(positions)
    mon = result[0]
    assert mon.trading_days == 2
    assert mon.trades == 2
    assert mon.total_pnl == pytest.approx(50.0)
    assert mon.avg_pnl == pytest.approx(25.0)
    assert mon.win_rate == pytest.approx(0.5)


def test_dow_win_rate_none_when_all_scratches():
    # commission == |pnl| → scratch → win_rate is None
    scratch = _pos(eid="s", entry_time=1776070800, exit_time=1776070860,
                   dollars_pnl=2.0, commission=2.0)
    result = bucket_by_day_of_week([scratch])
    assert result[0].win_rate is None


def test_dow_uses_session_date_not_entry_calendar_date():
    # 1776115800 = 2026-04-13 21:30 UTC = 16:30 CDT → session date 2026-04-14 (Tue)
    # Confirmed by existing test_bucket_uses_session_date_not_calendar
    positions = [_at(1776115800, eid="rollover", pnl=10.0)]
    result = bucket_by_day_of_week(positions)
    assert result[0].trades == 0   # Monday gets nothing
    assert result[1].trades == 1   # Tuesday gets the rollover trade


def test_dow_multiple_trades_same_day_count_as_one_trading_day():
    # Three trades all on 2026-04-13 (Mon) → trading_days == 1
    positions = [
        _at(1776070800, eid="a", pnl=10.0),
        _at(1776071400, eid="b", pnl=20.0),
        _at(1776072000, eid="c", pnl=30.0),
    ]
    result = bucket_by_day_of_week(positions)
    assert result[0].trading_days == 1
    assert result[0].trades == 3
    assert result[0].total_pnl == pytest.approx(60.0)
    assert result[0].avg_pnl == pytest.approx(60.0)  # 60 / 1 trading day


def test_dow_all_five_days():
    positions = [
        _at(1776070800, eid="mon", pnl=10.0),  # Mon
        _at(1776157200, eid="tue", pnl=20.0),  # Tue
        _at(1776243600, eid="wed", pnl=30.0),  # Wed
        _at(1776330000, eid="thu", pnl=40.0),  # Thu
        _at(1776416400, eid="fri", pnl=50.0),  # Fri
    ]
    result = bucket_by_day_of_week(positions)
    assert [b.trades for b in result] == [1, 1, 1, 1, 1]
    assert [b.total_pnl for b in result] == [10.0, 20.0, 30.0, 40.0, 50.0]
