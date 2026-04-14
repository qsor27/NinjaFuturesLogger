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


def test_session_date_filter_keeps_matching():
    # 2026-04-13 09:00 UTC == 04:00 CDT, session 2026-04-13
    p = _pos("a", 1776070800)
    out = apply_filters([p], PositionFilter(session_date=date(2026, 4, 13)))
    assert out == [p]


def test_session_date_filter_drops_other_dates():
    p = _pos("a", 1776070800)
    out = apply_filters([p], PositionFilter(session_date=date(2026, 4, 14)))
    assert out == []


def test_session_date_filter_handles_chicago_rollover():
    # 2026-04-13 21:30 UTC == 16:30 CDT, session 2026-04-14
    p = _pos("rollover", 1776115800)
    out = apply_filters([p], PositionFilter(session_date=date(2026, 4, 14)))
    assert out == [p]
    out = apply_filters([p], PositionFilter(session_date=date(2026, 4, 13)))
    assert out == []


def test_session_date_filter_none_passes_everything():
    p = _pos("a", 1776070800)
    out = apply_filters([p], PositionFilter())
    assert out == [p]
