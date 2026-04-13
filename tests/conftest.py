from pathlib import Path

import pytest

from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    (tmp_path / "inbox").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "logs").mkdir()
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
