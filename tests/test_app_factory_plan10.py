import time
from pathlib import Path

from app import create_app
from db import connect as _connect
from services.import_pipeline import ImportPipeline


def test_pipeline_is_registered_in_app_config(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    pipeline = app.config.get("FTL_IMPORT_PIPELINE")
    assert isinstance(pipeline, ImportPipeline)


def test_imports_blueprint_is_registered(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    client = app.test_client()
    resp = client.get("/api/imports/runs")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"runs": []}


def test_inbox_dir_is_in_app_config(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    assert Path(app.config["FTL_INBOX_DIR"]) == Path(tmp_config.inbox_dir)


def test_scheduler_has_archival_and_sweep_jobs_when_started(tmp_config):
    app, services = create_app(tmp_config, start_background=True)
    try:
        ids = {j.id for j in services.scheduler.get_jobs()}
        assert "heartbeat" in ids
        assert "import_safety_sweep" in ids
        assert "archive_completed_sessions" in ids
    finally:
        services.stop()


def test_watchdog_uses_tick_handler_when_started(tmp_config):
    app, services = create_app(tmp_config, start_background=True)
    try:
        assert services.observer_alive()
        assert app.config["FTL_IMPORT_PIPELINE"] is not None
    finally:
        services.stop()


def test_watchdog_drop_reaches_executions(tmp_config):
    app, services = create_app(tmp_config, start_background=True)
    try:
        header = (
            "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
            "Commission,Rate,Account,Connection,TradeValidation\n"
        )
        row = (
            "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,watchid,Entry,1 L,"
            "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
        )
        path = Path(tmp_config.inbox_dir) / "NinjaTrader_Executions_20260413.csv"
        path.write_text(header + row, encoding="utf-8")

        deadline = time.time() + 3.0
        inserted = 0
        while time.time() < deadline:
            conn = _connect(tmp_config.db_path)
            try:
                inserted = conn.execute(
                    "SELECT COUNT(*) FROM executions WHERE nt_execution_id = 'watchid'"
                ).fetchone()[0]
            finally:
                conn.close()
            if inserted == 1:
                break
            time.sleep(0.05)
        assert inserted == 1
    finally:
        services.stop()
