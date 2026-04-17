import pytest

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from models.position import Position
from services.position_filters import PositionFilter, apply_filters


def _pos(eid: str, entry_time: int, dollars_pnl: float = 10.0, side: str = "Long") -> Position:
    return Position(
        account="Sim",
        instrument="MNQ",
        entry_execution_id=eid,
        side=side,
        entry_time=entry_time,
        exit_time=entry_time + 60,
        quantity=1,
        entry_price=100.0,
        exit_price=101.0,
        points_pnl=1.0,
        dollars_pnl=dollars_pnl,
        commission=0.0,
        duration_minutes=1.0,
        execution_ids=[eid],
    )


def _ts(y: int, m: int, d: int, hour: int = 12, minute: int = 0, tz: str = "UTC") -> int:
    """Unix seconds for a wall-clock time in the given TZ."""
    return int(datetime(y, m, d, hour, minute, tzinfo=ZoneInfo(tz)).timestamp())


def test_session_date_from_inclusive_lower_bound():
    positions = [
        _pos("before", _ts(2026, 4, 13, 12)),
        _pos("boundary", _ts(2026, 4, 14, 12)),
        _pos("after", _ts(2026, 4, 15, 12)),
    ]
    out = apply_filters(positions, PositionFilter(session_date_from=date(2026, 4, 14)))
    assert [p.entry_execution_id for p in out] == ["boundary", "after"]


def test_session_date_to_inclusive_upper_bound():
    positions = [
        _pos("before", _ts(2026, 4, 13, 12)),
        _pos("boundary", _ts(2026, 4, 14, 12)),
        _pos("after", _ts(2026, 4, 15, 12)),
    ]
    out = apply_filters(positions, PositionFilter(session_date_to=date(2026, 4, 14)))
    assert [p.entry_execution_id for p in out] == ["before", "boundary"]


def test_session_date_from_and_to_compose():
    positions = [
        _pos("d12", _ts(2026, 4, 12, 12)),
        _pos("d13", _ts(2026, 4, 13, 12)),
        _pos("d14", _ts(2026, 4, 14, 12)),
        _pos("d15", _ts(2026, 4, 15, 12)),
    ]
    out = apply_filters(
        positions,
        PositionFilter(session_date_from=date(2026, 4, 13), session_date_to=date(2026, 4, 14)),
    )
    assert [p.entry_execution_id for p in out] == ["d13", "d14"]


def test_session_date_from_greater_than_to_returns_empty():
    positions = [_pos("x", _ts(2026, 4, 14, 12))]
    out = apply_filters(
        positions,
        PositionFilter(session_date_from=date(2026, 4, 15), session_date_to=date(2026, 4, 14)),
    )
    assert out == []


def test_day_of_week_filter_matches_session_date_weekday():
    # 2026-04-13 is a Monday (weekday 0).
    mon = _pos("mon", _ts(2026, 4, 13, 12))
    tue = _pos("tue", _ts(2026, 4, 14, 12))
    out = apply_filters([mon, tue], PositionFilter(day_of_week=0))
    assert [p.entry_execution_id for p in out] == ["mon"]


def test_day_of_week_filter_uses_session_date_not_utc_date():
    # 2026-04-12 (Sun) at 22:30 UTC == 17:30 CDT (post-17:00 rollover) →
    # session date 2026-04-13 (Mon).
    sun_evening = _pos("sun-evening", _ts(2026, 4, 12, 22, minute=30))
    # 2026-04-14 (Tue) at 12:00 UTC → session 2026-04-14 (Tue).
    tue_midday = _pos("tue-midday", _ts(2026, 4, 14, 12))
    out = apply_filters([sun_evening, tue_midday], PositionFilter(day_of_week=0))
    # Only the Sunday-evening entry should survive (rolls to Monday session).
    assert [p.entry_execution_id for p in out] == ["sun-evening"]


def test_hour_of_day_filter_matches_in_specified_tz():
    # 2026-04-14 18:00 UTC == 14:00 America/New_York (EDT, UTC-4).
    ny_14 = _pos("ny14", _ts(2026, 4, 14, 18))
    # 2026-04-14 12:00 UTC == 08:00 America/New_York.
    ny_08 = _pos("ny08", _ts(2026, 4, 14, 12))
    out = apply_filters(
        [ny_14, ny_08],
        PositionFilter(hour_of_day=14, hour_tz="America/New_York"),
    )
    assert [p.entry_execution_id for p in out] == ["ny14"]


def test_hour_of_day_filter_changes_with_tz():
    # 2026-04-14 18:00 UTC == 14:00 NY == 11:00 LA.
    p = _pos("p", _ts(2026, 4, 14, 18))
    out_ny = apply_filters([p], PositionFilter(hour_of_day=14, hour_tz="America/New_York"))
    out_la = apply_filters([p], PositionFilter(hour_of_day=14, hour_tz="America/Los_Angeles"))
    assert [x.entry_execution_id for x in out_ny] == ["p"]
    assert out_la == []


def test_hour_of_day_without_tz_raises():
    p = _pos("p", _ts(2026, 4, 14, 18))
    with pytest.raises(ValueError, match="hour_tz"):
        apply_filters([p], PositionFilter(hour_of_day=14))


def test_trades_per_day_keeps_only_days_with_matching_count():
    # Day 2026-04-13: 1 trade. Day 2026-04-14: 3 trades. Day 2026-04-15: 3 trades.
    positions = [
        _pos("mon-1", _ts(2026, 4, 13, 12)),
        _pos("tue-1", _ts(2026, 4, 14, 10)),
        _pos("tue-2", _ts(2026, 4, 14, 12)),
        _pos("tue-3", _ts(2026, 4, 14, 14)),
        _pos("wed-1", _ts(2026, 4, 15, 10)),
        _pos("wed-2", _ts(2026, 4, 15, 12)),
        _pos("wed-3", _ts(2026, 4, 15, 14)),
    ]
    out_3 = apply_filters(positions, PositionFilter(trades_per_day=3))
    assert sorted(p.entry_execution_id for p in out_3) == [
        "tue-1", "tue-2", "tue-3", "wed-1", "wed-2", "wed-3",
    ]
    out_1 = apply_filters(positions, PositionFilter(trades_per_day=1))
    assert [p.entry_execution_id for p in out_1] == ["mon-1"]


def test_trades_per_day_counts_after_other_filters():
    # Tue has 5 trades: 3 Long + 2 Short. With side=Long, the Tue count is 3.
    positions = [
        _pos("tue-L1", _ts(2026, 4, 14, 9), side="Long"),
        _pos("tue-L2", _ts(2026, 4, 14, 10), side="Long"),
        _pos("tue-L3", _ts(2026, 4, 14, 11), side="Long"),
        _pos("tue-S1", _ts(2026, 4, 14, 12), side="Short"),
        _pos("tue-S2", _ts(2026, 4, 14, 13), side="Short"),
        _pos("wed-L1", _ts(2026, 4, 15, 10), side="Long"),
    ]
    out = apply_filters(positions, PositionFilter(side="Long", trades_per_day=3))
    assert sorted(p.entry_execution_id for p in out) == ["tue-L1", "tue-L2", "tue-L3"]


def test_trades_per_day_none_passes_everything():
    positions = [_pos("a", _ts(2026, 4, 13, 12))]
    out = apply_filters(positions, PositionFilter(trades_per_day=None))
    assert out == positions
