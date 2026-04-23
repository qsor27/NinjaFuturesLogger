"""Round-trip guard: stats bucket count == drill-down position count.

For each drill-down-capable tile, seed a known set of executions, fetch the
stats bucket, then fetch /api/positions with the drill-down facet and assert
the counts match. Prevents silent divergence between aggregation and filter
logic.
"""

from app import create_app
from db import connect
from models.execution import Execution
from services.import_db import bulk_insert_executions


def _ex(exid, account, instrument, ts, side, action, ex_mark, pos_col):
    return Execution(
        nt_execution_id=exid,
        account=account,
        instrument=instrument,
        timestamp=ts,
        side=side,
        original_action=action,
        quantity=1,
        price=100.0,
        commission=0.0,
        entry_exit=ex_mark,
        position_after=pos_col,
        source_order_id=None,
        source_filename="f.csv",
        imported_at=ts,
    )


def _seed(db_path, execs):
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, execs)
    finally:
        conn.close()


def _utc_ts(y: int, m: int, d: int, hour: int = 12, minute: int = 0) -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return int(datetime(y, m, d, hour, minute, tzinfo=ZoneInfo("UTC")).timestamp())


# Known fixture: 3 closed positions on 2 distinct session dates.
# Mon 2026-04-13 12:00 UTC → session 2026-04-13 (Monday, weekday 0), hour 08 NY.
# Tue 2026-04-14 14:00 UTC → session 2026-04-14 (Tuesday, weekday 1), hour 10 NY.
# Tue 2026-04-14 16:00 UTC → session 2026-04-14 (Tuesday, weekday 1), hour 12 NY.
_MON = _utc_ts(2026, 4, 13, 12)
_TUE1 = _utc_ts(2026, 4, 14, 14)
_TUE2 = _utc_ts(2026, 4, 14, 16)
FIXTURE = [
    _ex("mon-in", "Sim", "MNQ", _MON, "Buy", "Buy", "Entry", "1 L"),
    _ex("mon-out", "Sim", "MNQ", _MON + 60, "Sell", "Sell", "Exit", "-"),
    _ex("tue1-in", "Sim", "MNQ", _TUE1, "Buy", "Buy", "Entry", "1 L"),
    _ex("tue1-out", "Sim", "MNQ", _TUE1 + 60, "Sell", "Sell", "Exit", "-"),
    _ex("tue2-in", "Sim", "MNQ", _TUE2, "Buy", "Buy", "Entry", "1 L"),
    _ex("tue2-out", "Sim", "MNQ", _TUE2 + 60, "Sell", "Sell", "Exit", "-"),
]


def test_day_of_week_roundtrip(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path, FIXTURE)
        c = app.test_client()

        stats = c.get("/api/stats/by-day-of-week").get_json()
        tue_bucket = next(b for b in stats["buckets"] if b["dow"] == 1)
        assert tue_bucket["trades"] == 2

        pos = c.get("/api/positions?day_of_week=1").get_json()
        assert pos["page"]["total"] == tue_bucket["trades"]
    finally:
        services.stop()


def test_by_hour_roundtrip(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path, FIXTURE)
        c = app.test_client()

        stats = c.get("/api/stats/by-hour?display_tz=America/New_York").get_json()
        tz = stats["timezone"]
        assert tz == "America/New_York"
        # Hour 10 NY = 14:00 UTC on 04-14 → one position.
        hour_10 = next(b for b in stats["buckets"] if b["hour"] == 10)
        assert hour_10["position_count"] == 1

        pos = c.get(f"/api/positions?hour_of_day=10&hour_tz={tz}").get_json()
        assert pos["page"]["total"] == hour_10["position_count"]
    finally:
        services.stop()


def test_trades_per_day_roundtrip(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path, FIXTURE)
        c = app.test_client()

        stats = c.get("/api/stats/by-trades-per-day").get_json()
        bucket_2 = next((b for b in stats["buckets"] if b["trades_per_day"] == 2), None)
        assert bucket_2 is not None
        assert bucket_2["total_trades"] == 2  # Tuesday has 2 trades

        pos = c.get("/api/positions?trades_per_day=2").get_json()
        assert pos["page"]["total"] == bucket_2["total_trades"]
    finally:
        services.stop()
