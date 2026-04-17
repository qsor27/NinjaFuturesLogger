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


def _ts(y: int, m: int, d: int, hour: int = 12, tz: str = "UTC") -> int:
    """Unix seconds for a wall-clock time in the given TZ."""
    return int(datetime(y, m, d, hour, tzinfo=ZoneInfo(tz)).timestamp())


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
