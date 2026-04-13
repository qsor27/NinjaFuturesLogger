from pathlib import Path

from app import create_app
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
