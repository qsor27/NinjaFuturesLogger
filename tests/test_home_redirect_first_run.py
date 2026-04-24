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


def test_root_redirects_to_wizard_when_preference_unset(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/first-run")


def test_root_redirects_to_positions_when_preference_set(client):
    set_preference(client.application.config["FTL_DB_PATH"], "first_run_complete", "true")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/positions")
