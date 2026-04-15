import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_SUBMITTED,
    JobExecutionEvent,
    JobSubmissionEvent,
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

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

    Uses PollingObserver (stat-based, 1s interval) instead of the native
    inotify Observer because Docker Desktop on Windows does not propagate
    host filesystem events through bind-mounted volumes into the container.
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
        self.observer: PollingObserver = PollingObserver(timeout=1.0)
        self._last_tick: int | None = None
        self._started: bool = False
        self._start_time: int = int(time.time())
        self._job_history: dict[str, deque] = {}
        self._job_in_flight: dict[str, int] = {}

    def _heartbeat(self) -> None:
        self._last_tick = int(time.time())

    def _on_job_submitted(self, event: JobSubmissionEvent) -> None:
        self._job_in_flight[event.job_id] = int(time.time() * 1000)

    def _on_job_finished(self, event: JobExecutionEvent) -> None:
        started_ms = self._job_in_flight.pop(event.job_id, None)
        now_ms = int(time.time() * 1000)
        duration_ms = (now_ms - started_ms) if started_ms is not None else None
        is_error = getattr(event, "exception", None) is not None
        record = {
            "started_at": (started_ms // 1000) if started_ms is not None else None,
            "duration_ms": duration_ms,
            "status": "error" if is_error else "success",
            "error": repr(event.exception) if is_error else None,
        }
        if event.job_id not in self._job_history:
            self._job_history[event.job_id] = deque(maxlen=20)
        self._job_history[event.job_id].appendleft(record)

    def start(self, *, handler=None) -> None:
        if self._started:
            return
        Path(self.config.inbox_dir).mkdir(parents=True, exist_ok=True)
        self.scheduler.add_job(
            self._heartbeat,
            trigger=IntervalTrigger(seconds=self.config.scheduler.heartbeat_seconds),
            id="heartbeat",
            replace_existing=True,
        )
        self.scheduler.add_listener(self._on_job_submitted, EVENT_JOB_SUBMITTED)
        self.scheduler.add_listener(self._on_job_finished, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        self.scheduler.start()
        use_handler = handler if handler is not None else _NoopHandler()
        self.observer.schedule(use_handler, self.config.inbox_dir, recursive=False)
        self.observer.start()
        self._started = True
        log.info(
            "background services started",
            extra={
                "max_workers": self.config.thread_pool.max_workers,
                "handler": type(use_handler).__name__,
            },
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

    def last_scheduler_tick(self) -> int | None:
        return self._last_tick

    # --- plan 17 introspection --------------------------------------------

    def system_health_snapshot(self) -> dict:
        """Snapshot of APScheduler jobs, thread pool, watchdog, uptime."""
        now = int(time.time())
        jobs = []
        for job in self.scheduler.get_jobs():
            history = list(self._job_history.get(job.id, []))
            avg_ms: int | None = None
            if history:
                durations = [r["duration_ms"] for r in history if r["duration_ms"] is not None]
                if durations:
                    avg_ms = sum(durations) // len(durations)
            last = history[0] if history else None
            next_run = job.next_run_time
            jobs.append(
                {
                    "job_id": job.id,
                    "name": job.name,
                    "trigger": str(job.trigger),
                    "next_run_time": next_run.timestamp() if next_run else None,
                    "last_run_at": last["started_at"] if last else None,
                    "last_run_status": last["status"] if last else None,
                    "last_run_error": last["error"] if last else None,
                    "avg_duration_ms": avg_ms,
                    "recent_runs": history[:5],
                }
            )

        try:
            pool_pending = self.pool._work_queue.qsize()  # type: ignore[attr-defined]
        except Exception:
            pool_pending = None
        try:
            pool_spawned = len(self.pool._threads)  # type: ignore[attr-defined]
        except Exception:
            pool_spawned = None

        return {
            "uptime_seconds": now - self._start_time,
            "started_at": self._start_time,
            "python_version": sys.version,
            "jobs": jobs,
            "pool": {
                "max_workers": self.config.thread_pool.max_workers,
                "spawned_threads": pool_spawned,
                "pending_queue": pool_pending,
            },
            "watchdog": {
                "alive": self.observer_alive(),
                "path": str(self.config.inbox_dir),
            },
        }

    def run_job_now(self, job_id: str) -> bool:
        """Submit a scheduled job's function to the thread pool for immediate execution.

        Does not alter the job's schedule. Returns True if the job was found,
        False if no job with that ID exists.
        """
        job = self.scheduler.get_job(job_id)
        if job is None:
            return False
        fn = job.func
        args = job.args
        kwargs = job.kwargs

        # APScheduler event listeners only fire for scheduler-driven runs, so a
        # direct pool.submit() would leave _job_history untouched and the data-
        # health panel's "Last run" field stuck at null. Wrap the call so it
        # records its own start/end into _job_history under the same key.
        def wrapped() -> None:
            started_ms = int(time.time() * 1000)
            is_error = False
            exc_repr: str | None = None
            try:
                fn(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — record anything
                is_error = True
                exc_repr = repr(e)
                raise
            finally:
                finished_ms = int(time.time() * 1000)
                record = {
                    "started_at": started_ms // 1000,
                    "duration_ms": finished_ms - started_ms,
                    "status": "error" if is_error else "success",
                    "error": exc_repr,
                }
                if job_id not in self._job_history:
                    self._job_history[job_id] = deque(maxlen=20)
                self._job_history[job_id].appendleft(record)

        self.pool.submit(wrapped)
        return True
