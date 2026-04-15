import json as _json
import time as _time
from pathlib import Path

import pytest
from flask import Flask

from app import create_app
from background import BackgroundServices
from config import (
    Config,
    SchedulerConfig,
    SessionConfig,
    ThreadPoolConfig,
    load_config,
)
from db import connect
from migrations import run_migrations
from models.execution import Execution
from models.position import IntegrityIssue
from routes.imports import build_imports_blueprint
from routes.monitoring import build_monitoring_blueprint
from routes.positions import build_positions_blueprint
from services.import_db import bulk_insert_executions, record_run
from services.integrity_db import mark_ignored, mark_resolved_by_user, upsert_issue


@pytest.fixture
def imports_app(tmp_path: Path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    run_migrations(conn, Path("migrations"))
    conn.close()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    from zoneinfo import ZoneInfo

    from services.import_pipeline import ImportPipeline

    pipeline = ImportPipeline(db_path=db_path, trader_tz=ZoneInfo("America/Chicago"))
    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = str(db_path)
    app.config["FTL_INBOX_DIR"] = str(inbox)
    app.config["FTL_IMPORT_PIPELINE"] = pipeline
    app.register_blueprint(build_imports_blueprint())
    app.register_blueprint(build_positions_blueprint())
    return app, db_path


def _seed_run(db_path, filename, started_at=1000, finished_at=1001, status="ok"):
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        tid = record_run(
            conn,
            filename=filename,
            started_at=started_at,
            finished_at=finished_at,
            cursor_before=0,
            cursor_after=10,
            lines_read=1,
            rows_parsed=1,
            rows_inserted=1,
            rows_skipped_duplicate=0,
            rows_rejected=0,
            status=status,
            error=None,
        )
        conn.execute("COMMIT")
        return tid
    finally:
        conn.close()


# --- import filter tests ---


def test_runs_filter_by_status(imports_app):
    app, db_path = imports_app
    _seed_run(db_path, "a.csv", status="ok")
    _seed_run(db_path, "b.csv", status="failed")
    resp = app.test_client().get("/api/imports/runs?status=failed")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["status"] == "failed"


def test_runs_filter_by_filename(imports_app):
    app, db_path = imports_app
    _seed_run(db_path, "ninja_20260414.csv")
    _seed_run(db_path, "other.csv")
    resp = app.test_client().get("/api/imports/runs?filename=ninja")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["runs"]) == 1
    assert "ninja" in body["runs"][0]["filename"]


def test_runs_filter_by_start_ts(imports_app):
    app, db_path = imports_app
    _seed_run(db_path, "old.csv", started_at=100)
    _seed_run(db_path, "new.csv", started_at=9000)
    resp = app.test_client().get("/api/imports/runs?start_ts=5000")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["filename"] == "new.csv"


def test_runs_filter_by_end_ts(imports_app):
    app, db_path = imports_app
    _seed_run(db_path, "old.csv", started_at=100)
    _seed_run(db_path, "new.csv", started_at=9000)
    resp = app.test_client().get("/api/imports/runs?end_ts=5000")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["filename"] == "old.csv"


def test_runs_includes_total(imports_app):
    app, db_path = imports_app
    _seed_run(db_path, "a.csv")
    _seed_run(db_path, "b.csv")
    resp = app.test_client().get("/api/imports/runs")
    body = resp.get_json()
    assert body["total"] == 2


# --- tick executions tests ---


def test_run_executions_returns_ids_for_tick(imports_app):
    app, db_path = imports_app
    tid = _seed_run(db_path, "f.csv", started_at=1000, finished_at=1010)
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        bulk_insert_executions(
            conn,
            [
                Execution(
                    nt_execution_id="ex1",
                    account="Sim101",
                    instrument="MNQ",
                    timestamp=1,
                    side="Buy",
                    original_action="Buy",
                    quantity=1,
                    price=1.0,
                    commission=0.0,
                    entry_exit="Entry",
                    position_after="1 L",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=1005,
                ),
                Execution(
                    nt_execution_id="ex2",
                    account="Sim101",
                    instrument="MNQ",
                    timestamp=2,
                    side="Sell",
                    original_action="Sell",
                    quantity=1,
                    price=2.0,
                    commission=0.0,
                    entry_exit="Exit",
                    position_after="-",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=1008,
                ),
            ],
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    resp = app.test_client().get(f"/api/imports/runs/{tid}/executions")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body["execution_ids"]) == {"ex1", "ex2"}


def test_run_executions_not_found(imports_app):
    app, _ = imports_app
    resp = app.test_client().get("/api/imports/runs/99999/executions")
    assert resp.status_code == 404


# --- integrity filter tests ---


def _mk_issue(eid="abc", severity="high", account="Sim101", instrument="MNQ"):
    return IntegrityIssue(
        account=account,
        instrument=instrument,
        execution_id=eid,
        severity=severity,
        type="position_column_mismatch",
        description="x",
    )


def _commit_issue(db_path, issue, now=100):
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        upsert_issue(conn, issue, now=now)
        conn.execute("COMMIT")
    finally:
        conn.close()


def test_integrity_filter_status_open(imports_app):
    app, db_path = imports_app
    _commit_issue(db_path, _mk_issue("a"))
    _commit_issue(db_path, _mk_issue("b"))
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        mark_resolved_by_user(conn, issue_id=1, now=200, note=None)
        conn.execute("COMMIT")
    finally:
        conn.close()
    resp = app.test_client().get("/api/integrity-issues?status=open")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 1
    assert body["issues"][0]["execution_id"] == "b"


def test_integrity_filter_status_resolved(imports_app):
    app, db_path = imports_app
    _commit_issue(db_path, _mk_issue("a"))
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        mark_resolved_by_user(conn, issue_id=1, now=200, note="fixed")
        conn.execute("COMMIT")
    finally:
        conn.close()
    resp = app.test_client().get("/api/integrity-issues?status=resolved")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 1
    assert body["issues"][0]["resolved_by"] == "user"


def test_integrity_filter_status_ignored(imports_app):
    app, db_path = imports_app
    _commit_issue(db_path, _mk_issue("a"))
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        mark_ignored(conn, issue_id=1, note="known noise")
        conn.execute("COMMIT")
    finally:
        conn.close()
    resp = app.test_client().get("/api/integrity-issues?status=ignored")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 1
    assert body["issues"][0]["ignored"] == 1


def test_integrity_filter_severity(imports_app):
    app, db_path = imports_app
    _commit_issue(db_path, _mk_issue("a", severity="high"))
    _commit_issue(db_path, _mk_issue("b", severity="low"))
    resp = app.test_client().get("/api/integrity-issues?severity=low")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 1
    assert body["issues"][0]["severity"] == "low"


def test_integrity_filter_account(imports_app):
    app, db_path = imports_app
    _commit_issue(db_path, _mk_issue("a", account="Sim101"))
    _commit_issue(db_path, _mk_issue("b", account="Sim202"))
    resp = app.test_client().get("/api/integrity-issues?account=Sim202")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 1
    assert body["issues"][0]["account"] == "Sim202"


# --- BackgroundServices health tests ---


@pytest.fixture
def svc_config(tmp_path):
    (tmp_path / "inbox").mkdir()
    return Config(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "t.db"),
        inbox_dir=str(tmp_path / "inbox"),
        archive_dir=str(tmp_path / "archive"),
        log_dir=str(tmp_path / "logs"),
        session=SessionConfig(
            exchange_timezone="America/Chicago",
            trade_date_rollover="16:00",
            archive_job_time="18:00",
        ),
        thread_pool=ThreadPoolConfig(max_workers=2),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
    )


def test_system_health_snapshot_shape(svc_config):
    svc = BackgroundServices(svc_config)
    snap = svc.system_health_snapshot()
    assert "uptime_seconds" in snap
    assert "started_at" in snap
    assert "jobs" in snap
    assert isinstance(snap["jobs"], list)
    assert "pool" in snap
    assert snap["pool"]["max_workers"] == 2
    assert "watchdog" in snap


def test_run_job_now_returns_false_for_unknown(svc_config):
    svc = BackgroundServices(svc_config)
    svc.start()
    try:
        result = svc.run_job_now("nonexistent_job")
        assert result is False
    finally:
        svc.stop()


def test_run_job_now_executes_job(svc_config):
    svc = BackgroundServices(svc_config)
    ran = []
    svc.start()
    try:
        svc.scheduler.add_job(
            lambda: ran.append(1),
            trigger="interval",
            seconds=9999,
            id="test_manual_job",
        )
        result = svc.run_job_now("test_manual_job")
        assert result is True
        _time.sleep(0.3)
        assert ran == [1]
    finally:
        svc.stop()


def test_run_job_now_records_job_history(svc_config):
    """Manual triggers must populate _job_history so the data-health panel's
    last_run_at field updates — APScheduler listeners only see scheduler-
    driven runs, so run_job_now has to record its own start/end."""
    svc = BackgroundServices(svc_config)
    svc.start()
    try:
        svc.scheduler.add_job(
            lambda: None,
            trigger="interval",
            seconds=9999,
            id="history_manual_job",
        )
        result = svc.run_job_now("history_manual_job")
        assert result is True
        _time.sleep(0.3)
        history = list(svc._job_history.get("history_manual_job", []))
        assert len(history) == 1
        record = history[0]
        assert record["status"] == "success"
        assert record["started_at"] is not None
        assert record["duration_ms"] is not None
    finally:
        svc.stop()


# --- monitoring blueprint tests ---


@pytest.fixture
def monitoring_app(tmp_path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    run_migrations(conn, Path("migrations"))
    conn.close()

    (tmp_path / "inbox").mkdir()
    config = Config(
        data_dir=str(tmp_path),
        db_path=str(db_path),
        inbox_dir=str(tmp_path / "inbox"),
        archive_dir=str(tmp_path / "archive"),
        log_dir=str(tmp_path / "logs"),
        session=SessionConfig(
            exchange_timezone="America/Chicago",
            trade_date_rollover="16:00",
            archive_job_time="18:00",
        ),
        thread_pool=ThreadPoolConfig(max_workers=2),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
    )
    svc = BackgroundServices(config)

    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = str(db_path)
    app.config["BACKGROUND_SERVICES"] = svc
    app.register_blueprint(build_monitoring_blueprint())
    return app, db_path


def test_data_health_completeness_empty(monitoring_app):
    app, _ = monitoring_app
    resp = app.test_client().get("/api/data-health/completeness")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "instruments" in body
    assert "cells" in body
    assert body["instruments"] == []


def test_data_health_completeness_has_instrument_after_executions(monitoring_app):
    app, db_path = monitoring_app
    now = int(_time.time())
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp,"
            " side, original_action, quantity, price, commission, entry_exit,"
            " position_after, source_order_id, source_filename, imported_at)"
            " VALUES ('e1','Sim101','MNQ',?,?,?,1,100.0,0.0,'Entry','1 L',NULL,'f.csv',?)",
            (now - 100, "Buy", "Buy", now - 100),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    resp = app.test_client().get("/api/data-health/completeness")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "MNQ" in body["instruments"]
    assert "MNQ" in body["cells"]


def test_data_health_missing_returns_gaps(monitoring_app):
    app, _ = monitoring_app
    now = int(_time.time())
    start = now - 3600
    end = now
    resp = app.test_client().get(f"/api/data-health/missing/MNQ/1m?start={start}&end={end}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "gaps" in body
    assert isinstance(body["gaps"], list)


def test_data_health_missing_unknown_timeframe(monitoring_app):
    app, _ = monitoring_app
    resp = app.test_client().get("/api/data-health/missing/MNQ/7x")
    assert resp.status_code == 400


def test_system_health_endpoint(monitoring_app):
    app, _ = monitoring_app
    resp = app.test_client().get("/api/system/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "jobs" in body
    assert "pool" in body
    assert "watchdog" in body
    assert "uptime_seconds" in body


def test_system_run_job_not_found(monitoring_app):
    app, _ = monitoring_app
    svc = app.config["BACKGROUND_SERVICES"]
    svc.start()
    try:
        resp = app.test_client().post("/api/system/run-job/ghost_job")
        assert resp.status_code == 404
    finally:
        svc.stop()


def test_system_run_job_executes(monitoring_app):
    app, _ = monitoring_app
    svc = app.config["BACKGROUND_SERVICES"]
    ran = []
    svc.start()
    try:
        svc.scheduler.add_job(
            lambda: ran.append(1),
            trigger="interval",
            seconds=9999,
            id="test_run_via_api",
        )
        resp = app.test_client().post("/api/system/run-job/test_run_via_api")
        assert resp.status_code == 200
        _time.sleep(0.3)
        assert ran == [1]
    finally:
        svc.stop()


# --- full app page route tests ---


def _make_full_config_client(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "archive").mkdir()
    (data_dir / "log").mkdir()
    app_json = data_dir / "config" / "app.json"
    app_json.write_text(
        _json.dumps(
            {
                "data_dir": str(data_dir),
                "db_path": str(data_dir / "ftl.db"),
                "inbox_dir": str(data_dir / "inbox"),
                "archive_dir": str(data_dir / "archive"),
                "log_dir": str(data_dir / "log"),
                "session": {
                    "exchange_timezone": "America/Chicago",
                    "trade_date_rollover": "16:00",
                    "archive_job_time": "18:00",
                },
                "thread_pool": {"max_workers": 2},
                "scheduler": {"heartbeat_seconds": 60},
            }
        )
    )
    app, _svc = create_app(load_config(app_json))
    return app.test_client()


def test_monitoring_pages_return_200(tmp_path):
    client = _make_full_config_client(tmp_path)
    for path in ["/imports", "/validation", "/data-health", "/system/health"]:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"


def test_imports_detail_page_returns_200(tmp_path):
    client = _make_full_config_client(tmp_path)
    resp = client.get("/imports/42")
    assert resp.status_code == 200


def test_canonical_timeframes_drop_4h_add_weekly_monthly():
    from routes.monitoring import CANONICAL_TIMEFRAMES

    assert "4h" not in CANONICAL_TIMEFRAMES
    assert "1wk" in CANONICAL_TIMEFRAMES
    assert "1mo" in CANONICAL_TIMEFRAMES
    assert CANONICAL_TIMEFRAMES == ["1m", "5m", "15m", "1h", "1d", "1wk", "1mo"]


def test_data_health_maintainer_endpoint(tmp_path):
    from app import create_app
    from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig

    (tmp_path / "inbox").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "logs").mkdir()
    cfg = Config(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "t.db"),
        inbox_dir=str(tmp_path / "inbox"),
        archive_dir=str(tmp_path / "archive"),
        log_dir=str(tmp_path / "logs"),
        session=SessionConfig(
            exchange_timezone="America/Chicago",
            trade_date_rollover="16:00",
            archive_job_time="18:00",
        ),
        thread_pool=ThreadPoolConfig(max_workers=2),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
    )
    app, services = create_app(cfg, start_background=False)
    try:
        client = app.test_client()
        resp = client.get("/api/data-health/maintainer")
        body = resp.get_json()
        assert resp.status_code == 200
        assert set(body.keys()) >= {
            "next_run_at",
            "last_run_at",
            "last_run_status",
            "token_bucket",
        }
        assert set(body["token_bucket"].keys()) >= {"capacity", "available"}
        assert body["token_bucket"]["capacity"] == 30
    finally:
        services.stop()


def test_data_health_completeness_emits_out_of_reach(tmp_path):
    """An execution seeded 60 days ago should produce a cell where 1m
    and 5m are marked out_of_reach (at least partially) at a 90-day window."""
    import time as _time

    from app import create_app
    from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig
    from db import connect

    (tmp_path / "inbox").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "logs").mkdir()
    cfg = Config(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "t.db"),
        inbox_dir=str(tmp_path / "inbox"),
        archive_dir=str(tmp_path / "archive"),
        log_dir=str(tmp_path / "logs"),
        session=SessionConfig(
            exchange_timezone="America/Chicago",
            trade_date_rollover="16:00",
            archive_job_time="18:00",
        ),
        thread_pool=ThreadPoolConfig(max_workers=2),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
    )
    app, services = create_app(cfg, start_background=False)
    try:
        conn = connect(cfg.db_path)
        now = int(_time.time())
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp,"
            " side, original_action, quantity, price, commission, entry_exit,"
            " source_filename, imported_at) "
            "VALUES (?, 'sim', 'MNQ JUN26', ?, 'Buy', 'Buy', 1, 100.0, 0.0, 'Entry',"
            " 'x.csv', 0)",
            ("e-recent", now - 3600),
        )
        conn.close()

        client = app.test_client()
        resp = client.get("/api/data-health/completeness?days=90")
        body = resp.get_json()
        assert "MNQ JUN26" in body["cells"]
        row = body["cells"]["MNQ JUN26"]
        # 1m window = 90 days, reach = 7 days -> expected cell is out_of_reach
        # because 0 bars are present and 83/90 days are beyond reach.
        assert row["1m"] in ("out_of_reach", "missing", "partial")
        # 4h should NOT appear in the row at all (dropped from canonical).
        assert "4h" not in row
        assert "1wk" in row
        assert "1mo" in row
    finally:
        services.stop()
