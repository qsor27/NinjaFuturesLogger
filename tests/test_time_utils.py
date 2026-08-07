from datetime import UTC, datetime

from services.time_utils import compute_session_date


def _utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_pre_rollover_central_time_is_same_day():
    # 2026-04-13 15:30 America/Chicago = 2026-04-13 20:30 UTC (CDT, UTC-5)
    ts = _utc(2026, 4, 13, 20, 30)
    assert compute_session_date(ts).isoformat() == "2026-04-13"


def test_post_rollover_central_time_is_next_day():
    # 2026-04-13 16:00 America/Chicago = 2026-04-13 21:00 UTC (CDT)
    ts = _utc(2026, 4, 13, 21, 0)
    assert compute_session_date(ts).isoformat() == "2026-04-14"


def test_just_before_rollover_is_same_day():
    # 2026-04-13 15:59 America/Chicago = 2026-04-13 20:59 UTC
    ts = _utc(2026, 4, 13, 20, 59)
    assert compute_session_date(ts).isoformat() == "2026-04-13"


def test_winter_standard_time_offset():
    # 2026-01-15 16:00 America/Chicago = 2026-01-15 22:00 UTC (CST, UTC-6)
    ts = _utc(2026, 1, 15, 22, 0)
    assert compute_session_date(ts).isoformat() == "2026-01-16"


def test_naive_datetime_is_rejected():
    try:
        compute_session_date(datetime(2026, 4, 13, 20, 30))
    except ValueError:
        return
    raise AssertionError("expected ValueError for naive datetime")


def test_session_date_of_position_uses_entry_time():
    from datetime import UTC, date, datetime

    from models.position import Position
    from services.time_utils import session_date_of

    def _pos(entry_time: int) -> Position:
        return Position(
            account="Sim101",
            instrument="MNQ",
            entry_execution_id="e1",
            side="Long",
            entry_time=entry_time,
            exit_time=None,
            quantity=1,
            entry_price=100.0,
            exit_price=None,
            points_pnl=None,
            dollars_pnl=None,
            commission=0.0,
            duration_minutes=None,
            execution_ids=["e1"],
        )

    # 15:00 Chicago (CST) -> same session date
    before_rollover = int(datetime(2026, 1, 5, 21, 0, tzinfo=UTC).timestamp())
    assert session_date_of(_pos(before_rollover)) == date(2026, 1, 5)
    # 16:30 Chicago -> next day's session
    after_rollover = int(datetime(2026, 1, 5, 22, 30, tzinfo=UTC).timestamp())
    assert session_date_of(_pos(after_rollover)) == date(2026, 1, 6)
