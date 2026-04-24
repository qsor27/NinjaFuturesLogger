from pathlib import Path

import pytest

from app import create_app
from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig
from services.preferences import set_preference


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


def test_nt_connection_initial_state(client, tmp_path):
    resp = client.get(f"/api/settings/nt-connection?documents={tmp_path}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["nt_found"] is False
    assert body["indicators_path"] is None
    assert body["indicator_installed_at"] is None
    assert body["inbox"] == {"files_count": 0, "last_csv_name": None, "last_csv_mtime": None}


def test_nt_connection_reports_installed_timestamp(client, tmp_path):
    set_preference(client.application.config["FTL_DB_PATH"], "indicator_installed_at", "1713830400")
    resp = client.get(f"/api/settings/nt-connection?documents={tmp_path}")
    assert resp.status_code == 200
    assert resp.get_json()["indicator_installed_at"] == 1713830400


def test_nt_connection_reflects_detected_nt(client, tmp_path):
    indicators = tmp_path / "NinjaTrader 8" / "bin" / "Custom" / "Indicators"
    indicators.mkdir(parents=True)
    resp = client.get(f"/api/settings/nt-connection?documents={tmp_path}")
    body = resp.get_json()
    assert body["nt_found"] is True
    assert body["indicators_path"].endswith("Indicators")
