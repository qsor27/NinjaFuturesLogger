from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from flask import Flask

from db import connect
from migrations import run_migrations
from models.execution import Execution
from routes.imports import build_imports_blueprint
from services.import_db import bulk_insert_executions, record_run, save_cursor
from services.import_pipeline import ImportPipeline

TZ = ZoneInfo("America/Chicago")


@pytest.fixture
def app_and_pipeline(tmp_path: Path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    run_migrations(conn, Path("migrations"))
    conn.close()

    inbox = tmp_path / "inbox"
    inbox.mkdir()

    pipeline = ImportPipeline(db_path=db_path, trader_tz=TZ)
    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = str(db_path)
    app.config["FTL_INBOX_DIR"] = str(inbox)
    app.config["FTL_IMPORT_PIPELINE"] = pipeline
    app.register_blueprint(build_imports_blueprint())
    return app, pipeline, db_path, inbox


def _seed_run(db_path: Path, filename: str, status: str = "ok") -> int:
    conn = connect(db_path)
    try:
        tid = record_run(
            conn,
            filename=filename, started_at=100, finished_at=101,
            cursor_before=0, cursor_after=100,
            lines_read=1, rows_parsed=1, rows_inserted=1,
            rows_skipped_duplicate=0, rows_rejected=0,
            status=status, error=None,
        )
        return tid
    finally:
        conn.close()


def test_get_runs_returns_latest_first(app_and_pipeline):
    app, pipeline, db_path, inbox = app_and_pipeline
    t1 = _seed_run(db_path, "a.csv")
    t2 = _seed_run(db_path, "b.csv")
    client = app.test_client()
    resp = client.get("/api/imports/runs")
    assert resp.status_code == 200
    body = resp.get_json()
    ids = [r["tick_id"] for r in body["runs"]]
    assert ids == [t2, t1]


def test_get_single_run(app_and_pipeline):
    app, pipeline, db_path, inbox = app_and_pipeline
    tid = _seed_run(db_path, "a.csv")
    client = app.test_client()
    resp = client.get(f"/api/imports/runs/{tid}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["tick_id"] == tid
    assert "rejects" in body
    assert body["rejects"] == []


def test_get_single_run_not_found(app_and_pipeline):
    app, _, _, _ = app_and_pipeline
    resp = app.test_client().get("/api/imports/runs/99999")
    assert resp.status_code == 404


def test_get_cursors(app_and_pipeline):
    app, _, db_path, _ = app_and_pipeline
    conn = connect(db_path)
    try:
        save_cursor(conn, "file.csv", byte_offset=42, file_mtime=0)
    finally:
        conn.close()
    resp = app.test_client().get("/api/imports/cursors")
    assert resp.status_code == 200
    body = resp.get_json()
    assert any(c["filename"] == "file.csv" and c["byte_offset"] == 42 for c in body["cursors"])


def test_get_rejects(app_and_pipeline):
    app, _, db_path, _ = app_and_pipeline
    tid = _seed_run(db_path, "a.csv")
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO import_rejects (tick_id, line_number, raw_line, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (tid, 3, "oops", "bad", 0),
        )
    finally:
        conn.close()
    resp = app.test_client().get("/api/imports/rejects")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["rejects"]) == 1
    assert body["rejects"][0]["line_number"] == 3


def test_scan_triggers_ingest(app_and_pipeline):
    app, pipeline, db_path, inbox = app_and_pipeline
    header = (
        "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
        "Commission,Rate,Account,Connection,TradeValidation\n"
    )
    row = (
        "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,scanid,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
    )
    (Path(inbox) / "NinjaTrader_Executions_20260413.csv").write_text(
        header + row, encoding="utf-8"
    )
    resp = app.test_client().post("/api/imports/scan")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ticked"] >= 1
    conn = connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == 1
    finally:
        conn.close()


def test_rollback_deletes_rows(app_and_pipeline):
    app, pipeline, db_path, inbox = app_and_pipeline
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, [
            Execution(
                nt_execution_id="del1", account="Sim101", instrument="MNQ",
                timestamp=1, side="Buy", original_action="Buy",
                quantity=1, price=1.0, commission=0.0, entry_exit="Entry",
                position_after="1 L", source_order_id=None,
                source_filename="f.csv", imported_at=1,
            ),
            Execution(
                nt_execution_id="keep1", account="Sim101", instrument="MNQ",
                timestamp=2, side="Sell", original_action="Sell",
                quantity=1, price=2.0, commission=0.0, entry_exit="Exit",
                position_after="-", source_order_id=None,
                source_filename="f.csv", imported_at=1,
            ),
        ])
    finally:
        conn.close()
    resp = app.test_client().post(
        "/api/executions/rollback", json={"execution_ids": ["del1"]}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["deleted"] == 1
    conn = connect(db_path)
    try:
        remaining = [
            r[0] for r in conn.execute(
                "SELECT nt_execution_id FROM executions"
            ).fetchall()
        ]
        assert remaining == ["keep1"]
    finally:
        conn.close()


def test_rollback_rejects_bad_body(app_and_pipeline):
    app, *_ = app_and_pipeline
    resp = app.test_client().post("/api/executions/rollback", json={})
    assert resp.status_code == 400
