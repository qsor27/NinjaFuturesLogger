from pathlib import Path

import pytest
from flask import Flask

from db import connect
from migrations import run_migrations
from models.execution import Execution
from models.position import IntegrityIssue
from routes.imports import build_imports_blueprint
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

import time as _time

from background import BackgroundServices
from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig


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
