import json
from pathlib import Path

import pytest

from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig
from db import connect
from migrations import run_migrations
from services.instruments import set_registry_path


@pytest.fixture(autouse=True)
def _reset_instrument_registry():
    """Restore the default registry path after every test so tests that
    call set_registry_path(tmp_path/…) don't leak into later tests."""
    yield
    set_registry_path(Path("data/config/instruments.json"))


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    (tmp_path / "inbox").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "config").mkdir()

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

    # Write the app.json file so save_filter_default can update it
    app_json = tmp_path / "config" / "app.json"
    app_json.write_text(json.dumps(cfg.model_dump()), encoding="utf-8")

    return cfg


@pytest.fixture
def migrated_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    try:
        run_migrations(conn, Path("migrations"))
    finally:
        conn.close()
    return db_path
