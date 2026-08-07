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


def test_background_services_accepts_injected_handler(tmp_config):
    from background import BackgroundServices

    services = BackgroundServices(tmp_config)
    pipeline = MagicMock()
    services.start(handler=TickHandler(pipeline))
    try:
        time.sleep(0.05)
        assert services.observer_alive()
    finally:
        services.stop()
