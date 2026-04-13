import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from config import Config
from logging_config import get_logger

log = get_logger("background")


class _NoopHandler(FileSystemEventHandler):
    """Placeholder. Plan 10 replaces this with the import tick handler."""


class BackgroundServices:
    """Single owner of every long-lived background thread in the process.

    Per doc 03: one APScheduler, one watchdog Observer, one bounded
    ThreadPoolExecutor. The application factory holds a reference to this
    object and calls start()/stop() at process boundaries.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.scheduler: BackgroundScheduler = BackgroundScheduler(
            timezone=config.session.exchange_timezone
        )
        self.pool: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=config.thread_pool.max_workers,
            thread_name_prefix="ftl-pool",
        )
        self.observer: Observer = Observer()
        self._last_tick: Optional[int] = None
        self._started: bool = False

    def _heartbeat(self) -> None:
        self._last_tick = int(time.time())

    def start(self) -> None:
        if self._started:
            return
        Path(self.config.inbox_dir).mkdir(parents=True, exist_ok=True)
        self.scheduler.add_job(
            self._heartbeat,
            trigger=IntervalTrigger(seconds=self.config.scheduler.heartbeat_seconds),
            id="heartbeat",
            replace_existing=True,
        )
        self.scheduler.start()
        self.observer.schedule(_NoopHandler(), self.config.inbox_dir, recursive=False)
        self.observer.start()
        self._started = True
        log.info(
            "background services started",
            extra={"max_workers": self.config.thread_pool.max_workers},
        )

    def stop(self) -> None:
        if not self._started:
            return
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            log.exception("scheduler shutdown raised")
        try:
            self.observer.stop()
            self.observer.join(timeout=5)
        except Exception:
            log.exception("observer shutdown raised")
        try:
            self.pool.shutdown(wait=True, cancel_futures=True)
        except Exception:
            log.exception("pool shutdown raised")
        self._started = False
        log.info("background services stopped")

    # --- introspection used by /healthz -----------------------------------

    def scheduler_running(self) -> bool:
        return self._started and self.scheduler.running

    def observer_alive(self) -> bool:
        return self._started and self.observer.is_alive()

    def pool_max_workers(self) -> int:
        return self.config.thread_pool.max_workers

    def last_scheduler_tick(self) -> Optional[int]:
        return self._last_tick
