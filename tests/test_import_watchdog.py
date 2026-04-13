import time
from pathlib import Path
from unittest.mock import MagicMock

from watchdog.events import DirModifiedEvent, FileCreatedEvent, FileModifiedEvent

from services.import_watchdog import TickHandler


def test_tick_handler_calls_ingest_on_created(tmp_path: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text("", encoding="utf-8")
    pipeline = MagicMock()
    handler = TickHandler(pipeline)
    handler.on_created(FileCreatedEvent(str(path)))
    pipeline.ingest_tick.assert_called_once_with(path)


def test_tick_handler_calls_ingest_on_modified(tmp_path: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text("", encoding="utf-8")
    pipeline = MagicMock()
    handler = TickHandler(pipeline)
    handler.on_modified(FileModifiedEvent(str(path)))
    pipeline.ingest_tick.assert_called_once_with(path)


def test_tick_handler_ignores_non_matching_filenames(tmp_path: Path):
    path = tmp_path / "some_other_file.csv"
    path.write_text("", encoding="utf-8")
    pipeline = MagicMock()
    handler = TickHandler(pipeline)
    handler.on_modified(FileModifiedEvent(str(path)))
    pipeline.ingest_tick.assert_not_called()


def test_tick_handler_ignores_directory_events(tmp_path: Path):
    pipeline = MagicMock()
    handler = TickHandler(pipeline)
    handler.on_modified(DirModifiedEvent(str(tmp_path)))
    pipeline.ingest_tick.assert_not_called()


def test_tick_handler_swallows_pipeline_errors(tmp_path: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text("", encoding="utf-8")
    pipeline = MagicMock()
    pipeline.ingest_tick.side_effect = RuntimeError("boom")
    handler = TickHandler(pipeline)
    handler.on_modified(FileModifiedEvent(str(path)))
    assert pipeline.ingest_tick.called


def test_background_services_accepts_injected_handler(tmp_path: Path):
    from background import BackgroundServices
    from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig

    cfg = Config(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "t.db"),
        inbox_dir=str(tmp_path / "inbox"),
        archive_dir=str(tmp_path / "archive"),
        log_dir=str(tmp_path / "logs"),
        session=SessionConfig(exchange_timezone="America/Chicago",
                              trade_date_rollover="16:00", archive_job_time="18:00"),
        thread_pool=ThreadPoolConfig(max_workers=2),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
    )
    Path(cfg.inbox_dir).mkdir()
    services = BackgroundServices(cfg)
    pipeline = MagicMock()
    services.start(handler=TickHandler(pipeline))
    try:
        time.sleep(0.05)
        assert services.observer_alive()
    finally:
        services.stop()
