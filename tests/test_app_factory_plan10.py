from pathlib import Path

from db import connect as _connect
from services.import_pipeline import ImportPipeline
from tests.conftest import wait_until, write_ninja_csv


def test_pipeline_is_registered_in_app_config(app):
    pipeline = app.config.get("FTL_IMPORT_PIPELINE")
    assert isinstance(pipeline, ImportPipeline)


def test_imports_blueprint_is_registered(app):
    client = app.test_client()
    resp = client.get("/api/imports/runs")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"runs": [], "total": 0}


def test_inbox_dir_is_in_app_config(app, tmp_config):
    assert Path(app.config["FTL_INBOX_DIR"]) == Path(tmp_config.inbox_dir)


def test_scheduler_has_archival_and_sweep_jobs_when_started(started_app_and_services):
    app, services = started_app_and_services
    ids = {j.id for j in services.scheduler.get_jobs()}
    assert "heartbeat" in ids
    assert "import_safety_sweep" in ids
    assert "archive_completed_sessions" in ids


def test_watchdog_uses_tick_handler_when_started(started_app_and_services):
    app, services = started_app_and_services
    assert services.observer_alive()
    assert app.config["FTL_IMPORT_PIPELINE"] is not None


def test_watchdog_drop_reaches_executions(started_app_and_services, tmp_config):
    app, services = started_app_and_services
    row = (
        "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,watchid,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
    )
    path = Path(tmp_config.inbox_dir) / "NinjaTrader_Executions_20260413.csv"
    write_ninja_csv(path, [row])

    def _row_landed() -> bool:
        conn = _connect(tmp_config.db_path)
        try:
            return (
                conn.execute(
                    "SELECT COUNT(*) FROM executions WHERE nt_execution_id = 'watchid'"
                ).fetchone()[0]
                == 1
            )
        finally:
            conn.close()

    assert wait_until(_row_landed)
