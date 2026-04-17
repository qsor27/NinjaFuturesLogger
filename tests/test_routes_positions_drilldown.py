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


def _mon_tue_executions():
    # Monday 2026-04-13 12:00 UTC entry+exit.
    # Tuesday 2026-04-14 12:00 UTC entry+exit.
    mon = _utc_ts(2026, 4, 13, 12)
    tue = _utc_ts(2026, 4, 14, 12)
    return [
        _ex("mon-in", "Sim", "MNQ", mon, "Buy", "Buy", "Entry", "1 L"),
        _ex("mon-out", "Sim", "MNQ", mon + 60, "Sell", "Sell", "Exit", "-"),
        _ex("tue-in", "Sim", "MNQ", tue, "Buy", "Buy", "Entry", "1 L"),
        _ex("tue-out", "Sim", "MNQ", tue + 60, "Sell", "Sell", "Exit", "-"),
    ]


def test_day_of_week_filter_happy_path(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path, _mon_tue_executions())
        resp = app.test_client().get("/api/positions?day_of_week=0")
        assert resp.status_code == 200
        positions = resp.get_json()["positions"]
        assert {p["entry_execution_id"] for p in positions} == {"mon-in"}
    finally:
        services.stop()


def test_day_of_week_out_of_range_returns_400(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/positions?day_of_week=5")
        assert resp.status_code == 400
        assert "day_of_week" in resp.get_json()["error"]
    finally:
        services.stop()


def test_hour_of_day_requires_hour_tz(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/positions?hour_of_day=14")
        assert resp.status_code == 400
        assert "hour_tz" in resp.get_json()["error"]
    finally:
        services.stop()


def test_hour_of_day_happy_path(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path, _mon_tue_executions())
        # Entries are 12:00 UTC == 08:00 America/New_York, not 14:00.
        resp_14 = app.test_client().get("/api/positions?hour_of_day=14&hour_tz=America/New_York")
        assert resp_14.status_code == 200
        assert resp_14.get_json()["page"]["total"] == 0

        resp_8 = app.test_client().get("/api/positions?hour_of_day=8&hour_tz=America/New_York")
        assert resp_8.status_code == 200
        assert resp_8.get_json()["page"]["total"] == 2
    finally:
        services.stop()


def test_hour_of_day_out_of_range_returns_400(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/positions?hour_of_day=24&hour_tz=America/New_York")
        assert resp.status_code == 400
        assert "hour_of_day" in resp.get_json()["error"]
    finally:
        services.stop()


def test_hour_tz_bad_value_returns_400(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/positions?hour_of_day=14&hour_tz=Not/A_Zone")
        assert resp.status_code == 400
        assert "hour_tz" in resp.get_json()["error"]
    finally:
        services.stop()


def test_trades_per_day_filter_happy_path(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path, _mon_tue_executions())  # 1 position each day
        resp = app.test_client().get("/api/positions?trades_per_day=1")
        assert resp.status_code == 200
        assert resp.get_json()["page"]["total"] == 2
        resp0 = app.test_client().get("/api/positions?trades_per_day=5")
        assert resp0.get_json()["page"]["total"] == 0
    finally:
        services.stop()


def test_trades_per_day_must_be_positive_int(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/positions?trades_per_day=0")
        assert resp.status_code == 400
        assert "trades_per_day" in resp.get_json()["error"]
    finally:
        services.stop()


def test_session_date_range_happy_path(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path, _mon_tue_executions())
        resp = app.test_client().get(
            "/api/positions?session_date_from=2026-04-14&session_date_to=2026-04-14"
        )
        positions = resp.get_json()["positions"]
        assert {p["entry_execution_id"] for p in positions} == {"tue-in"}
    finally:
        services.stop()


def test_session_date_range_bad_iso_returns_400(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/positions?session_date_from=04/14/2026")
        assert resp.status_code == 400
        assert "session_date_from" in resp.get_json()["error"]
    finally:
        services.stop()
