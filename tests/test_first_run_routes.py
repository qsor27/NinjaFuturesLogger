from pathlib import Path

import pytest

from app import create_app
from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig
from services.preferences import get_preference


def _build_config(tmp_path: Path) -> Config:
    data = tmp_path / "data"
    (data / "config").mkdir(parents=True)
    (data / "inbox").mkdir()
    (data / "archive").mkdir()
    (data / "logs").mkdir()
    return Config(
        db_path=str(data / "app.db"),
        data_dir=str(data),
        inbox_dir=str(data / "inbox"),
        archive_dir=str(data / "archive"),
        log_dir=str(data / "logs"),
        session=SessionConfig(
            exchange_timezone="America/Chicago",
            source_timezone="America/Chicago",
            trade_date_rollover="17:00",
            archive_job_time="18:00",
        ),
        thread_pool=ThreadPoolConfig(max_workers=4),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
        display_timezone=None,
        theme="dark",
    )


@pytest.fixture
def client(tmp_path):
    cfg = _build_config(tmp_path)
    app, services = create_app(cfg, start_background=False)
    try:
        with app.test_client() as c:
            yield c
    finally:
        services.stop()


def test_first_run_page_renders(client):
    resp = client.get("/first-run")
    assert resp.status_code == 200
    assert b"first-run-root" in resp.data


def test_detect_nt_returns_not_found_for_empty_override(client, tmp_path):
    resp = client.get(f"/api/first-run/detect-nt?documents={tmp_path}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"found": False, "indicators_path": None}


def test_detect_nt_returns_found_when_indicators_dir_exists(client, tmp_path):
    indicators = tmp_path / "NinjaTrader 8" / "bin" / "Custom" / "Indicators"
    indicators.mkdir(parents=True)
    resp = client.get(f"/api/first-run/detect-nt?documents={tmp_path}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["found"] is True
    assert body["indicators_path"].endswith("Indicators")


def test_install_indicator_copies_file_and_sets_preference(client, tmp_path, monkeypatch):
    dest_dir = tmp_path / "indicators"
    dest_dir.mkdir()

    # Point the source-file resolver at a synthesized source
    src = tmp_path / "src" / "ExecutionExporter.cs"
    src.parent.mkdir()
    src.write_text("// source")
    monkeypatch.setenv("FTL_NT_INDICATOR_SOURCE", str(src))

    resp = client.post(
        "/api/first-run/install-indicator",
        json={"dest_dir": str(dest_dir), "on_conflict": "overwrite"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["dest_path"].endswith("ExecutionExporter.cs")
    assert (dest_dir / "ExecutionExporter.cs").read_text() == "// source"

    db_path = client.application.config["FTL_DB_PATH"]
    assert get_preference(db_path, "indicator_installed_at") is not None


def test_install_indicator_rejects_missing_body(client):
    resp = client.post("/api/first-run/install-indicator", json={})
    assert resp.status_code == 400


def test_install_indicator_rejects_bad_on_conflict_value(client, tmp_path):
    dest_dir = tmp_path / "indicators"
    dest_dir.mkdir()
    resp = client.post(
        "/api/first-run/install-indicator",
        json={"dest_dir": str(dest_dir), "on_conflict": "nuke"},
    )
    assert resp.status_code == 400


def test_inbox_status_empty(client):
    resp = client.get("/api/first-run/inbox-status")
    assert resp.status_code == 200
    assert resp.get_json() == {
        "files_count": 0,
        "last_csv_name": None,
        "last_csv_mtime": None,
    }


def test_inbox_status_reports_latest(client):
    inbox = Path(client.application.config["FTL_INBOX_DIR"])
    (inbox / "NinjaTrader_Executions_20250101.csv").write_text("header\n")
    (inbox / "NinjaTrader_Executions_20250102.csv").write_text("header\n")
    resp = client.get("/api/first-run/inbox-status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["files_count"] == 2
    assert body["last_csv_name"] in {
        "NinjaTrader_Executions_20250101.csv",
        "NinjaTrader_Executions_20250102.csv",
    }
    assert isinstance(body["last_csv_mtime"], int)


def test_complete_sets_preference(client):
    db_path = client.application.config["FTL_DB_PATH"]
    assert get_preference(db_path, "first_run_complete") is None
    resp = client.post("/api/first-run/complete")
    assert resp.status_code == 200
    assert resp.get_json() == {"success": True}
    assert get_preference(db_path, "first_run_complete") == "true"


def test_complete_is_idempotent(client):
    db_path = client.application.config["FTL_DB_PATH"]
    client.post("/api/first-run/complete")
    resp = client.post("/api/first-run/complete")
    assert resp.status_code == 200
    assert get_preference(db_path, "first_run_complete") == "true"


def test_indicator_path_reports_existing_file(client, tmp_path, monkeypatch):
    src = tmp_path / "src" / "ExecutionExporter.cs"
    src.parent.mkdir()
    src.write_text("// fixture")
    monkeypatch.setenv("FTL_NT_INDICATOR_SOURCE", str(src))

    resp = client.get("/api/first-run/indicator-path")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["path"] == str(src)
    assert body["exists"] is True


def test_indicator_path_reports_missing_file(client, tmp_path, monkeypatch):
    missing = tmp_path / "nope.cs"
    monkeypatch.setenv("FTL_NT_INDICATOR_SOURCE", str(missing))

    resp = client.get("/api/first-run/indicator-path")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["path"] == str(missing)
    assert body["exists"] is False
