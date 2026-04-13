from pathlib import Path

from background import BackgroundServices
from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig


def _cfg(tmp_path: Path) -> Config:
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


def test_start_and_stop_lifecycle(tmp_path: Path):
    (tmp_path / "inbox").mkdir()
    services = BackgroundServices(_cfg(tmp_path))
    services.start()
    try:
        assert services.scheduler_running()
        assert services.observer_alive()
        assert services.pool_max_workers() == 2
    finally:
        services.stop()
    assert not services.scheduler_running()
    assert not services.observer_alive()


def test_heartbeat_job_is_registered(tmp_path: Path):
    (tmp_path / "inbox").mkdir()
    services = BackgroundServices(_cfg(tmp_path))
    services.start()
    try:
        job_ids = [j.id for j in services.scheduler.get_jobs()]
        assert "heartbeat" in job_ids
    finally:
        services.stop()


def test_last_scheduler_tick_updates(tmp_path: Path):
    (tmp_path / "inbox").mkdir()
    services = BackgroundServices(_cfg(tmp_path))
    services.start()
    try:
        services._heartbeat()
        assert services.last_scheduler_tick() is not None
    finally:
        services.stop()
