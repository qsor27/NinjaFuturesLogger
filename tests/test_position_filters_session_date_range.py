from datetime import date

from models.position import Position
from services.position_filters import PositionFilter, apply_filters


def _pos(eid: str, entry_time: int) -> Position:
    return Position(
        account="Sim",
        instrument="MNQ",
        entry_execution_id=eid,
        side="Long",
        entry_time=entry_time,
        exit_time=entry_time + 60,
        quantity=1,
        entry_price=100.0,
        exit_price=101.0,
        points_pnl=1.0,
        dollars_pnl=10.0,
        commission=0.0,
        duration_minutes=1.0,
        execution_ids=[eid],
    )


# 2026-04-13 09:00 UTC -> 04:00 CDT -> session 2026-04-13
P_13 = _pos("a", 1776070800)
# 2026-04-13 21:30 UTC -> 16:30 CDT -> session 2026-04-14 (post-17:00 rollover)
P_14_rollover = _pos("rollover", 1776115800)


def test_range_both_bounds_inclusive_keeps_matching():
    out = apply_filters(
        [P_13],
        PositionFilter(
            session_date_from=date(2026, 4, 13),
            session_date_to=date(2026, 4, 13),
        ),
    )
    assert out == [P_13]


def test_range_both_bounds_drops_outside():
    out = apply_filters(
        [P_13],
        PositionFilter(
            session_date_from=date(2026, 4, 14),
            session_date_to=date(2026, 4, 20),
        ),
    )
    assert out == []


def test_range_only_from_is_open_ended_above():
    out = apply_filters(
        [P_13, P_14_rollover],
        PositionFilter(session_date_from=date(2026, 4, 14)),
    )
    assert out == [P_14_rollover]


def test_range_only_to_is_open_ended_below():
    out = apply_filters(
        [P_13, P_14_rollover],
        PositionFilter(session_date_to=date(2026, 4, 13)),
    )
    assert out == [P_13]


def test_range_neither_bound_passes_everything():
    out = apply_filters([P_13, P_14_rollover], PositionFilter())
    assert out == [P_13, P_14_rollover]


def test_range_handles_chicago_rollover():
    out = apply_filters(
        [P_14_rollover],
        PositionFilter(
            session_date_from=date(2026, 4, 14),
            session_date_to=date(2026, 4, 14),
        ),
    )
    assert out == [P_14_rollover]
    out = apply_filters(
        [P_14_rollover],
        PositionFilter(
            session_date_from=date(2026, 4, 13),
            session_date_to=date(2026, 4, 13),
        ),
    )
    assert out == []
