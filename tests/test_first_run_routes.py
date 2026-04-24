from pathlib import Path

import pytest

from app import create_app
from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig


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
