from pathlib import Path

from watchdog.events import (
    DirCreatedEvent,
    DirModifiedEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileSystemEventHandler,
)

from logging_config import get_logger

log = get_logger("import.watchdog")

_PREFIX = "NinjaTrader_Executions_"
_SUFFIX = ".csv"


class TickHandler(FileSystemEventHandler):
    """Route watchdog events into `ImportPipeline.ingest_tick`."""

    def __init__(self, pipeline) -> None:
        self.pipeline = pipeline

    def on_created(self, event):
        if isinstance(event, DirCreatedEvent | DirModifiedEvent):
            return
        if isinstance(event, FileCreatedEvent):
            self._dispatch(event.src_path)

    def on_modified(self, event):
        if isinstance(event, DirCreatedEvent | DirModifiedEvent):
            return
        if isinstance(event, FileModifiedEvent):
            self._dispatch(event.src_path)

    def _dispatch(self, src_path: str) -> None:
        p = Path(src_path)
        if not (p.name.startswith(_PREFIX) and p.name.endswith(_SUFFIX)):
            return
        try:
            self.pipeline.ingest_tick(p)
        except Exception:
            log.exception("ingest_tick failed in watchdog thread", extra={"csv_name": p.name})
