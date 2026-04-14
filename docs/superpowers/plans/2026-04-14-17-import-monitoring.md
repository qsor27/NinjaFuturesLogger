# Plan 17 — Import Monitoring, Validation & Data Health

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver four operator-facing dashboard pages — `/imports`, `/validation`, `/data-health`, `/system/health` — plus the API routes and BackgroundServices introspection they depend on.

**Architecture:** All four pages are read surfaces over tables and in-process state produced by earlier features. No new business logic, no new DB tables. The data-health completeness query is computed live from `bars` + `gap_detection.find_gaps`. System health is exposed via a new `system_health_snapshot()` on `BackgroundServices`.

**Tech Stack:** Flask blueprints, vanilla ES modules (no bundler), Jinja2 templates extending `base.html`, APScheduler 3.x event listeners, SQLite.

---

## File Map

**Created:**
- `routes/monitoring.py` — data-health + system-health API routes + page routes for all four pages
- `templates/imports.html` — imports list page shell
- `templates/imports_detail.html` — import tick detail page shell
- `templates/validation.html` — validation page shell
- `templates/data_health.html` — data health matrix shell
- `templates/system_health.html` — system health dashboard shell
- `static/js/imports.js` — imports list + detail JS
- `static/js/validation.js` — validation page JS
- `static/js/data_health.js` — data health page JS
- `static/js/system_health.js` — system health page JS
- `tests/test_routes_monitoring.py` — all tests for monitoring routes

**Modified:**
- `background.py` — add job history tracker, `system_health_snapshot()`, `run_job_now()`
- `routes/imports.py` — add filter params to `GET /api/imports/runs`, add `GET /api/imports/runs/{tick_id}/executions`
- `routes/positions.py` — add filter params to `GET /api/integrity-issues`
- `app.py` — register monitoring blueprint, pass `FTL_BACKGROUND_SERVICES` alias
- `routes/pages.py` — add page routes for the four new pages (moved to monitoring.py instead)
- `templates/base.html` — add nav links for Imports, Validation, Data Health, System

---

## Task 1: Enhance `/api/imports/runs` with filter params

**Files:**
- Modify: `routes/imports.py`
- Test: `tests/test_routes_monitoring.py` (create file)

The current endpoint only supports `limit`/`offset`. The imports page needs date range, filename, and status filters.

- [ ] **Step 1: Write the failing test**

Create `tests/test_routes_monitoring.py`:

```python
from pathlib import Path

import pytest
from flask import Flask

from db import connect
from migrations import run_migrations
from routes.imports import build_imports_blueprint
from routes.positions import build_positions_blueprint
from services.import_db import bulk_insert_executions, record_run
from models.execution import Execution


@pytest.fixture
def imports_app(tmp_path: Path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    run_migrations(conn, Path("migrations"))
    conn.close()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    from zoneinfo import ZoneInfo
    from services.import_pipeline import ImportPipeline
    pipeline = ImportPipeline(db_path=db_path, trader_tz=ZoneInfo("America/Chicago"))
    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = str(db_path)
    app.config["FTL_INBOX_DIR"] = str(inbox)
    app.config["FTL_IMPORT_PIPELINE"] = pipeline
    app.register_blueprint(build_imports_blueprint())
    app.register_blueprint(build_positions_blueprint())
    return app, db_path


def _seed_run(db_path, filename, started_at=1000, finished_at=1001, status="ok"):
    conn = connect(db_path)
    try:
        tid = record_run(
            conn,
            filename=filename,
            started_at=started_at,
            finished_at=finished_at,
            cursor_before=0,
            cursor_after=10,
            lines_read=1,
            rows_parsed=1,
            rows_inserted=1,
            rows_skipped_duplicate=0,
            rows_rejected=0,
            status=status,
            error=None,
        )
        return tid
    finally:
        conn.close()


# --- import filter tests ---

def test_runs_filter_by_status(imports_app):
    app, db_path = imports_app
    _seed_run(db_path, "a.csv", status="ok")
    _seed_run(db_path, "b.csv", status="failed")
    resp = app.test_client().get("/api/imports/runs?status=failed")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["status"] == "failed"


def test_runs_filter_by_filename(imports_app):
    app, db_path = imports_app
    _seed_run(db_path, "ninja_20260414.csv")
    _seed_run(db_path, "other.csv")
    resp = app.test_client().get("/api/imports/runs?filename=ninja")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["runs"]) == 1
    assert "ninja" in body["runs"][0]["filename"]


def test_runs_filter_by_start_ts(imports_app):
    app, db_path = imports_app
    _seed_run(db_path, "old.csv", started_at=100)
    _seed_run(db_path, "new.csv", started_at=9000)
    resp = app.test_client().get("/api/imports/runs?start_ts=5000")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["filename"] == "new.csv"


def test_runs_filter_by_end_ts(imports_app):
    app, db_path = imports_app
    _seed_run(db_path, "old.csv", started_at=100)
    _seed_run(db_path, "new.csv", started_at=9000)
    resp = app.test_client().get("/api/imports/runs?end_ts=5000")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["filename"] == "old.csv"
```

- [ ] **Step 2: Run to verify it fails**

```
pytest tests/test_routes_monitoring.py::test_runs_filter_by_status -v
```

Expected: FAIL (no filter support yet)

- [ ] **Step 3: Update `routes/imports.py` — add filter params**

Replace the `list_runs` function:

```python
@bp.get("/api/imports/runs")
def list_runs():
    limit = min(int(request.args.get("limit", "50")), 500)
    offset = max(int(request.args.get("offset", "0")), 0)
    start_ts = request.args.get("start_ts")
    end_ts = request.args.get("end_ts")
    filename = request.args.get("filename")
    status = request.args.get("status")

    clauses: list[str] = []
    params: list = []
    if start_ts is not None:
        clauses.append("started_at >= ?")
        params.append(int(start_ts))
    if end_ts is not None:
        clauses.append("started_at <= ?")
        params.append(int(end_ts))
    if filename:
        clauses.append("filename LIKE ?")
        params.append(f"%{filename}%")
    if status:
        clauses.append("status = ?")
        params.append(status)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        "SELECT tick_id, filename, started_at, finished_at, cursor_before,"
        " cursor_after, lines_read, rows_parsed, rows_inserted,"
        " rows_skipped_duplicate, rows_rejected, status, error "
        f"FROM import_runs {where} ORDER BY tick_id DESC LIMIT ? OFFSET ?"
    )
    conn = _db()
    try:
        rows = conn.execute(sql, (*params, limit, offset)).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM import_runs {where}", params
        ).fetchone()[0]
    finally:
        conn.close()
    return jsonify({"runs": [dict(r) for r in rows], "total": total})
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_routes_monitoring.py::test_runs_filter_by_status tests/test_routes_monitoring.py::test_runs_filter_by_filename tests/test_routes_monitoring.py::test_runs_filter_by_start_ts tests/test_routes_monitoring.py::test_runs_filter_by_end_ts -v
```

Expected: 4 PASS

- [ ] **Step 5: Verify existing imports tests still pass**

```
pytest tests/test_routes_imports.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add routes/imports.py tests/test_routes_monitoring.py
git commit -m "feat(plan17): add filter params to GET /api/imports/runs"
```

---

## Task 2: Add `GET /api/imports/runs/{tick_id}/executions`

The rollback button on the detail page needs the execution IDs that were inserted by a specific tick. We derive these from `source_filename` + `imported_at` time window (the per-path lock in `ImportPipeline` guarantees ticks on the same file are serialized, so the time window is exact).

**Files:**
- Modify: `routes/imports.py`
- Test: `tests/test_routes_monitoring.py`

- [ ] **Step 1: Add test**

Append to `tests/test_routes_monitoring.py`:

```python
def test_run_executions_returns_ids_for_tick(imports_app):
    app, db_path = imports_app
    tid = _seed_run(db_path, "f.csv", started_at=1000, finished_at=1010)
    # Seed two executions with imported_at in the tick's window
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, [
            Execution(
                nt_execution_id="ex1",
                account="Sim101",
                instrument="MNQ",
                timestamp=1,
                side="Buy",
                original_action="Buy",
                quantity=1,
                price=1.0,
                commission=0.0,
                entry_exit="Entry",
                position_after="1 L",
                source_order_id=None,
                source_filename="f.csv",
                imported_at=1005,
            ),
            Execution(
                nt_execution_id="ex2",
                account="Sim101",
                instrument="MNQ",
                timestamp=2,
                side="Sell",
                original_action="Sell",
                quantity=1,
                price=2.0,
                commission=0.0,
                entry_exit="Exit",
                position_after="-",
                source_order_id=None,
                source_filename="f.csv",
                imported_at=1008,
            ),
        ])
    finally:
        conn.close()
    resp = app.test_client().get(f"/api/imports/runs/{tid}/executions")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body["execution_ids"]) == {"ex1", "ex2"}


def test_run_executions_not_found(imports_app):
    app, _ = imports_app
    resp = app.test_client().get("/api/imports/runs/99999/executions")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

```
pytest tests/test_routes_monitoring.py::test_run_executions_returns_ids_for_tick -v
```

Expected: FAIL (endpoint doesn't exist)

- [ ] **Step 3: Add endpoint to `routes/imports.py`**

Add after `get_run`:

```python
@bp.get("/api/imports/runs/<int:tick_id>/executions")
def get_run_executions(tick_id: int):
    conn = _db()
    try:
        run = conn.execute(
            "SELECT filename, started_at, finished_at FROM import_runs WHERE tick_id = ?",
            (tick_id,),
        ).fetchone()
        if run is None:
            return jsonify({"error": "not found"}), 404
        # Use source_filename + imported_at window to find executions for this tick.
        # The per-path lock in ImportPipeline serializes ticks on the same file,
        # so this window is unambiguous in practice. +5s buffer for clock skew.
        rows = conn.execute(
            "SELECT nt_execution_id FROM executions "
            "WHERE source_filename = ? AND imported_at BETWEEN ? AND ?",
            (run["filename"], run["started_at"], run["finished_at"] + 5),
        ).fetchall()
    finally:
        conn.close()
    return jsonify({"execution_ids": [r["nt_execution_id"] for r in rows]})
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_routes_monitoring.py::test_run_executions_returns_ids_for_tick tests/test_routes_monitoring.py::test_run_executions_not_found -v
```

Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add routes/imports.py tests/test_routes_monitoring.py
git commit -m "feat(plan17): add GET /api/imports/runs/{tick_id}/executions"
```

---

## Task 3: Enhance `/api/integrity-issues` with filter params

The validation page needs to filter by status (open/resolved/ignored), severity, account, and instrument. The current endpoint only returns open issues.

**Files:**
- Modify: `routes/positions.py`
- Test: `tests/test_routes_monitoring.py`

- [ ] **Step 1: Add tests**

Append to `tests/test_routes_monitoring.py`:

```python
from models.position import IntegrityIssue
from services.integrity_db import upsert_issue, mark_resolved_by_user, mark_ignored


def _mk_issue(eid="abc", severity="high", account="Sim101", instrument="MNQ"):
    return IntegrityIssue(
        account=account,
        instrument=instrument,
        execution_id=eid,
        severity=severity,
        type="position_column_mismatch",
        description="x",
    )


def test_integrity_filter_status_open(imports_app):
    app, db_path = imports_app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _mk_issue("a"), now=100)
        upsert_issue(conn, _mk_issue("b"), now=100)
        mark_resolved_by_user(conn, issue_id=1, now=200, note=None)
    finally:
        conn.close()
    resp = app.test_client().get("/api/integrity-issues?status=open")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 1
    assert body["issues"][0]["execution_id"] == "b"


def test_integrity_filter_status_resolved(imports_app):
    app, db_path = imports_app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _mk_issue("a"), now=100)
        mark_resolved_by_user(conn, issue_id=1, now=200, note="fixed")
    finally:
        conn.close()
    resp = app.test_client().get("/api/integrity-issues?status=resolved")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 1
    assert body["issues"][0]["resolved_by"] == "user"


def test_integrity_filter_status_ignored(imports_app):
    app, db_path = imports_app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _mk_issue("a"), now=100)
        mark_ignored(conn, issue_id=1, note="known noise")
    finally:
        conn.close()
    resp = app.test_client().get("/api/integrity-issues?status=ignored")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 1
    assert body["issues"][0]["ignored"] == 1


def test_integrity_filter_severity(imports_app):
    app, db_path = imports_app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _mk_issue("a", severity="high"), now=100)
        upsert_issue(conn, _mk_issue("b", severity="low"), now=100)
    finally:
        conn.close()
    resp = app.test_client().get("/api/integrity-issues?severity=low")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 1
    assert body["issues"][0]["severity"] == "low"


def test_integrity_filter_account(imports_app):
    app, db_path = imports_app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _mk_issue("a", account="Sim101"), now=100)
        upsert_issue(conn, _mk_issue("b", account="Sim202"), now=100)
    finally:
        conn.close()
    resp = app.test_client().get("/api/integrity-issues?account=Sim202")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 1
    assert body["issues"][0]["account"] == "Sim202"
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_routes_monitoring.py::test_integrity_filter_status_open -v
```

Expected: FAIL (no filter support)

- [ ] **Step 3: Update `list_integrity` in `routes/positions.py`**

Find the `list_integrity` function (around line 203) and replace it:

```python
@bp.get("/api/integrity-issues")
def list_integrity():
    status = request.args.get("status", "open")  # open|resolved|ignored|all
    severity = request.args.get("severity")
    account = request.args.get("account")
    instrument = request.args.get("instrument")

    clauses: list[str] = []
    params: list = []

    if status == "open":
        clauses.append("resolved_at IS NULL AND ignored = 0")
    elif status == "resolved":
        clauses.append("resolved_at IS NOT NULL")
    elif status == "ignored":
        clauses.append("ignored = 1")
    # status == "all": no clause

    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    if account:
        clauses.append("account = ?")
        params.append(account)
    if instrument:
        clauses.append("instrument = ?")
        params.append(instrument)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        f"SELECT * FROM integrity_issues {where} "
        "ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,"
        " detected_at DESC LIMIT 500"
    )
    conn = connect(_db_path())
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return jsonify({"issues": [dict(r) for r in rows]})
```

- [ ] **Step 4: Run new tests**

```
pytest tests/test_routes_monitoring.py -k "integrity_filter" -v
```

Expected: 5 PASS

- [ ] **Step 5: Verify existing integrity tests still pass**

```
pytest tests/test_routes_integrity.py -v
```

Expected: all PASS (the default `status=open` preserves existing behavior)

- [ ] **Step 6: Commit**

```bash
git add routes/positions.py tests/test_routes_monitoring.py
git commit -m "feat(plan17): add filter params to GET /api/integrity-issues"
```

---

## Task 4: BackgroundServices job history + system health snapshot

The system health page needs APScheduler job metadata (last run time, status, avg duration), thread pool state, watchdog liveness, and process uptime.

**Files:**
- Modify: `background.py`
- Test: `tests/test_routes_monitoring.py`

- [ ] **Step 1: Add tests**

Append to `tests/test_routes_monitoring.py`:

```python
import time as _time
from background import BackgroundServices
from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig


@pytest.fixture
def svc_config(tmp_path):
    (tmp_path / "inbox").mkdir()
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


def test_system_health_snapshot_shape(svc_config):
    svc = BackgroundServices(svc_config)
    snap = svc.system_health_snapshot()
    assert "uptime_seconds" in snap
    assert "started_at" in snap
    assert "jobs" in snap
    assert isinstance(snap["jobs"], list)
    assert "pool" in snap
    assert snap["pool"]["max_workers"] == 2
    assert "watchdog" in snap


def test_run_job_now_returns_false_for_unknown(svc_config):
    svc = BackgroundServices(svc_config)
    svc.start()
    try:
        result = svc.run_job_now("nonexistent_job")
        assert result is False
    finally:
        svc.stop()


def test_run_job_now_executes_job(svc_config):
    svc = BackgroundServices(svc_config)
    ran = []
    svc.start()
    try:
        svc.scheduler.add_job(
            lambda: ran.append(1),
            trigger="interval",
            seconds=9999,
            id="test_manual_job",
        )
        result = svc.run_job_now("test_manual_job")
        assert result is True
        _time.sleep(0.2)  # let the pool thread finish
        assert ran == [1]
    finally:
        svc.stop()
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_routes_monitoring.py::test_system_health_snapshot_shape -v
```

Expected: FAIL (method doesn't exist)

- [ ] **Step 3: Update `background.py`**

Replace the entire file content:

```python
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
    The trade-off is ~1s detection latency vs. the native ~10ms; for a
    directory that holds at most a handful of NinjaTrader CSVs this is
    invisible.
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
        # job_id -> deque(maxlen=20) of {"started_at", "duration_ms", "status", "error"}
        self._job_history: dict[str, deque] = {}
        # job_id -> epoch ms when submitted (in-flight)
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
        self.scheduler.add_listener(
            self._on_job_finished, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )
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
        self.pool.submit(job.func, *job.args, **job.kwargs)
        return True
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_routes_monitoring.py::test_system_health_snapshot_shape tests/test_routes_monitoring.py::test_run_job_now_returns_false_for_unknown tests/test_routes_monitoring.py::test_run_job_now_executes_job -v
```

Expected: 3 PASS

- [ ] **Step 5: Verify all existing background tests pass**

```
pytest tests/test_background.py tests/test_health.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add background.py tests/test_routes_monitoring.py
git commit -m "feat(plan17): add job history tracking and system_health_snapshot to BackgroundServices"
```

---

## Task 5: Create `routes/monitoring.py` — data-health + system-health API routes

**Files:**
- Create: `routes/monitoring.py`
- Test: `tests/test_routes_monitoring.py`

- [ ] **Step 1: Add tests for data-health completeness**

Append to `tests/test_routes_monitoring.py`:

```python
import time as _time_mod
from flask import Flask as _Flask
from routes.monitoring import build_monitoring_blueprint


@pytest.fixture
def monitoring_app(tmp_path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    run_migrations(conn, Path("migrations"))
    conn.close()

    config = Config(
        data_dir=str(tmp_path),
        db_path=str(db_path),
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
    svc = BackgroundServices(config)

    app = _Flask(__name__)
    app.config["FTL_DB_PATH"] = str(db_path)
    app.config["BACKGROUND_SERVICES"] = svc
    app.register_blueprint(build_monitoring_blueprint())
    return app, db_path


def test_data_health_completeness_empty(monitoring_app):
    app, _ = monitoring_app
    resp = app.test_client().get("/api/data-health/completeness")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "instruments" in body
    assert "cells" in body
    assert body["instruments"] == []


def test_data_health_completeness_has_instrument_after_executions(monitoring_app):
    app, db_path = monitoring_app
    now = int(_time_mod.time())
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp,"
            " side, original_action, quantity, price, commission, entry_exit,"
            " position_after, source_order_id, source_filename, imported_at)"
            " VALUES ('e1','Sim101','MNQ',?,?,?,1,100.0,0.0,'Entry','1 L',NULL,'f.csv',?)",
            (now - 100, "Buy", "Buy", now - 100),
        )
    finally:
        conn.close()
    resp = app.test_client().get("/api/data-health/completeness")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "MNQ" in body["instruments"]
    assert "MNQ" in body["cells"]


def test_data_health_missing_returns_gaps(monitoring_app):
    app, _ = monitoring_app
    now = int(_time_mod.time())
    start = now - 3600
    end = now
    resp = app.test_client().get(
        f"/api/data-health/missing/MNQ/1m?start={start}&end={end}"
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "gaps" in body
    assert isinstance(body["gaps"], list)


def test_system_health_endpoint(monitoring_app):
    app, _ = monitoring_app
    resp = app.test_client().get("/api/system/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "jobs" in body
    assert "pool" in body
    assert "watchdog" in body
    assert "uptime_seconds" in body


def test_system_run_job_not_found(monitoring_app):
    app, _ = monitoring_app
    resp = app.test_client().post("/api/system/run-job/ghost_job")
    assert resp.status_code == 404


def test_system_run_job_executes(monitoring_app):
    app, _ = monitoring_app
    svc = app.config["BACKGROUND_SERVICES"]
    ran = []
    svc.start()
    try:
        svc.scheduler.add_job(
            lambda: ran.append(1),
            trigger="interval",
            seconds=9999,
            id="test_run_via_api",
        )
        resp = app.test_client().post("/api/system/run-job/test_run_via_api")
        assert resp.status_code == 200
        _time_mod.sleep(0.3)
        assert ran == [1]
    finally:
        svc.stop()
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_routes_monitoring.py::test_data_health_completeness_empty -v
```

Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Create `routes/monitoring.py`**

```python
import time
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger
from services.instruments import default_session
from services.ohlc.gap_detection import _expected_slots, find_gaps, timeframe_seconds
from services.ohlc.store import list_times

log = get_logger("http.monitoring")

CANONICAL_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
DATA_HEALTH_LOOKBACK_DAYS = 7
ACTIVE_INSTRUMENTS_LOOKBACK_DAYS = 90


def build_monitoring_blueprint() -> Blueprint:
    bp = Blueprint("monitoring", __name__)

    def _db_path() -> str:
        return current_app.config["FTL_DB_PATH"]

    def _services():
        return current_app.config["BACKGROUND_SERVICES"]

    # ------------------------------------------------------------------ #
    # Data health                                                         #
    # ------------------------------------------------------------------ #

    @bp.get("/api/data-health/completeness")
    def data_health_completeness():
        days = int(request.args.get("days", str(DATA_HEALTH_LOOKBACK_DAYS)))
        now = int(time.time())
        start = now - days * 86400
        cutoff = now - ACTIVE_INSTRUMENTS_LOOKBACK_DAYS * 86400

        conn = connect(_db_path())
        try:
            rows = conn.execute(
                "SELECT DISTINCT instrument FROM executions WHERE timestamp >= ? ORDER BY instrument",
                (cutoff,),
            ).fetchall()
            instruments = [r["instrument"] for r in rows]

            cells: dict[str, dict[str, str]] = {}
            for instrument in instruments:
                cells[instrument] = {}
                for tf in CANONICAL_TIMEFRAMES:
                    cells[instrument][tf] = _cell_status(
                        conn, instrument=instrument, timeframe=tf, start=start, end=now
                    )
        finally:
            conn.close()

        return jsonify(
            {
                "instruments": instruments,
                "timeframes": CANONICAL_TIMEFRAMES,
                "cells": cells,
                "window_start": start,
                "window_end": now,
                "days": days,
            }
        )

    @bp.get("/api/data-health/missing/<instrument>/<timeframe>")
    def data_health_missing(instrument: str, timeframe: str):
        try:
            timeframe_seconds(timeframe)
        except ValueError:
            return jsonify({"error": f"unknown timeframe: {timeframe}"}), 400

        now = int(time.time())
        default_days = DATA_HEALTH_LOOKBACK_DAYS
        start = int(request.args.get("start", now - default_days * 86400))
        end = int(request.args.get("end", now))

        conn = connect(_db_path())
        try:
            gaps = find_gaps(conn, instrument=instrument, timeframe=timeframe, start=start, end=end)
            expected = _expected_slots(instrument, timeframe, start, end)
            present = list_times(conn, instrument=instrument, timeframe=timeframe, start=start, end=end)
        finally:
            conn.close()

        return jsonify(
            {
                "instrument": instrument,
                "timeframe": timeframe,
                "start": start,
                "end": end,
                "expected_slots": len(expected),
                "present_bars": len(present),
                "gaps": [{"start": g[0], "end": g[1]} for g in gaps],
            }
        )

    # ------------------------------------------------------------------ #
    # System health                                                       #
    # ------------------------------------------------------------------ #

    @bp.get("/api/system/health")
    def system_health():
        snap = _services().system_health_snapshot()
        return jsonify(snap)

    @bp.post("/api/system/run-job/<job_id>")
    def run_job(job_id: str):
        ok = _services().run_job_now(job_id)
        if not ok:
            return jsonify({"error": f"job '{job_id}' not found"}), 404
        return jsonify({"ok": True, "job_id": job_id})

    return bp


def _cell_status(conn, *, instrument: str, timeframe: str, start: int, end: int) -> str:
    """Compute completeness status for one instrument × timeframe cell."""
    expected = _expected_slots(instrument, timeframe, start, end)
    if not expected:
        return "session_closed"
    gaps = find_gaps(conn, instrument=instrument, timeframe=timeframe, start=start, end=end)
    if not gaps:
        return "complete"
    present = list_times(conn, instrument=instrument, timeframe=timeframe, start=start, end=end)
    return "missing" if not present else "partial"
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_routes_monitoring.py -k "data_health or system_health or system_run" -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add routes/monitoring.py tests/test_routes_monitoring.py
git commit -m "feat(plan17): data-health and system-health API routes"
```

---

## Task 6: Wire up blueprint, add nav links, add page routes

**Files:**
- Modify: `app.py`
- Modify: `routes/pages.py`
- Modify: `templates/base.html`

- [ ] **Step 1: Add test**

Append to `tests/test_routes_monitoring.py`:

```python
from app import create_app
from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig


def _make_full_config(tmp_path):
    (tmp_path / "inbox").mkdir(exist_ok=True)
    (tmp_path / "archive").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
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


def test_monitoring_pages_return_200(tmp_path):
    config = _make_full_config(tmp_path)
    app, _ = create_app(config)
    client = app.test_client()
    for path in ["/imports", "/validation", "/data-health", "/system/health"]:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
```

- [ ] **Step 2: Run to verify it fails**

```
pytest tests/test_routes_monitoring.py::test_monitoring_pages_return_200 -v
```

Expected: FAIL (pages not registered)

- [ ] **Step 3: Update `app.py` — import and register monitoring blueprint**

After the existing blueprint imports, add:

```python
from routes.monitoring import build_monitoring_blueprint
```

After `app.register_blueprint(build_stats_blueprint())`, add:

```python
app.register_blueprint(build_monitoring_blueprint())
```

- [ ] **Step 4: Update `routes/pages.py` — add four new page routes**

Add imports and routes after the existing `reports_page` route:

```python
@bp.get("/imports")
def imports_list():
    return render_template("imports.html")


@bp.get("/imports/<int:tick_id>")
def imports_detail(tick_id: int):
    return render_template("imports_detail.html", tick_id=tick_id)


@bp.get("/validation")
def validation_page():
    return render_template("validation.html")


@bp.get("/data-health")
def data_health_page():
    return render_template("data_health.html")


@bp.get("/system/health")
def system_health_page():
    return render_template("system_health.html")
```

The function `build_pages_blueprint` already returns `bp` at the end — add these routes before that `return bp`.

- [ ] **Step 5: Update `templates/base.html` — add nav links**

Replace the `<header>` block:

```html
    <header>
      <a href="/positions">Positions</a>
      <a href="/statistics">Statistics</a>
      <a href="/reports">Reports</a>
      <a href="/links">Link Groups</a>
      <a href="/settings">Settings</a>
      <a href="/imports">Imports</a>
      <a href="/validation">Validation</a>
      <a href="/data-health">Data Health</a>
      <a href="/system/health">System</a>
    </header>
```

- [ ] **Step 6: Create minimal placeholder templates**

Create `templates/imports.html`:

```html
{% extends "base.html" %}
{% block title %}Import History — FTL{% endblock %}
{% block content %}
<h1>Import History</h1>
<div id="cursors-band"></div>
<div class="filters" id="filters-bar"></div>
<div id="runs-table"></div>
{% endblock %}
{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/imports.js') }}"></script>
{% endblock %}
```

Create `templates/imports_detail.html`:

```html
{% extends "base.html" %}
{% block title %}Import Tick {{ tick_id }} — FTL{% endblock %}
{% block content %}
<h1>Import Tick #{{ tick_id }}</h1>
<div id="tick-detail" data-tick-id="{{ tick_id }}"></div>
<div id="rejects-table"></div>
<div id="rollback-section"></div>
{% endblock %}
{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/imports.js') }}"></script>
{% endblock %}
```

Create `templates/validation.html`:

```html
{% extends "base.html" %}
{% block title %}Validation — FTL{% endblock %}
{% block content %}
<h1>Validation</h1>
<div class="info-banner">
  Issues are re-evaluated on every import tick. Issues that no longer hold
  are marked system-resolved automatically. Ignored issues stay ignored until
  you unignore them.
</div>
<div class="filters" id="filters-bar"></div>
<div id="issues-table"></div>
{% endblock %}
{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/validation.js') }}"></script>
{% endblock %}
```

Create `templates/data_health.html`:

```html
{% extends "base.html" %}
{% block title %}Data Health — FTL{% endblock %}
{% block content %}
<h1>Data Health</h1>
<div id="sources-band"></div>
<div id="completeness-matrix"></div>
<div id="detail-panel" style="display:none"></div>
{% endblock %}
{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/data_health.js') }}"></script>
{% endblock %}
```

Create `templates/system_health.html`:

```html
{% extends "base.html" %}
{% block title %}System Health — FTL{% endblock %}
{% block content %}
<h1>System Health</h1>
<div id="healthz-section"></div>
<h2>APScheduler Jobs</h2>
<div id="jobs-table"></div>
<h2>Thread Pool</h2>
<div id="pool-section"></div>
<h2>Watchdog Observer</h2>
<div id="watchdog-section"></div>
<h2>Uptime</h2>
<div id="uptime-section"></div>
{% endblock %}
{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/system_health.js') }}"></script>
{% endblock %}
```

- [ ] **Step 7: Run the page test**

```
pytest tests/test_routes_monitoring.py::test_monitoring_pages_return_200 -v
```

Expected: PASS

- [ ] **Step 8: Run all tests to catch regressions**

```
pytest -x -q
```

Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add app.py routes/pages.py templates/imports.html templates/imports_detail.html templates/validation.html templates/data_health.html templates/system_health.html
git commit -m "feat(plan17): register monitoring blueprint, add nav links, create page shells"
```

---

## Task 7: Imports list & detail page — JS

**Files:**
- Create: `static/js/imports.js`

- [ ] **Step 1: Create `static/js/imports.js`**

```javascript
// imports.js — handles both /imports (list) and /imports/:tick_id (detail)

const isDetail = document.getElementById("tick-detail") !== null;

if (isDetail) {
  initDetail();
} else {
  initList();
}

// ------------------------------------------------------------------ //
// List page                                                           //
// ------------------------------------------------------------------ //

async function initList() {
  await renderCursorsBand();
  renderFilters();
  await loadRuns();
  document.getElementById("scan-btn")?.addEventListener("click", onScanNow);
}

async function renderCursorsBand() {
  const band = document.getElementById("cursors-band");
  if (!band) return;
  const resp = await fetch("/api/imports/cursors");
  const { cursors } = await resp.json();
  if (!cursors.length) {
    band.innerHTML = "<p style='color:#888'>No active inbox files.</p>";
    return;
  }
  const rows = cursors.map((c) => {
    const cursor = c.byte_offset.toLocaleString();
    const modified = c.last_modified
      ? new Date(c.last_modified * 1000).toLocaleString()
      : "—";
    return `<tr>
      <td>${escHtml(c.filename)}</td>
      <td>${cursor} bytes</td>
      <td>${modified}</td>
    </tr>`;
  });
  band.innerHTML = `
    <h3 style="margin-top:0">Active Inbox Files</h3>
    <button id="scan-btn" style="margin-bottom:8px">Scan Now</button>
    <table>
      <thead><tr><th>File</th><th>Cursor Position</th><th>Last Modified</th></tr></thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;
}

function renderFilters() {
  const bar = document.getElementById("filters-bar");
  if (!bar) return;
  const sevenDaysAgo = Math.floor(Date.now() / 1000) - 7 * 86400;
  bar.innerHTML = `
    <label>From<input type="date" id="f-start" value="${epochToDateInput(sevenDaysAgo)}"></label>
    <label>To<input type="date" id="f-end"></label>
    <label>Filename<input type="text" id="f-filename" placeholder="partial match"></label>
    <label>Status
      <select id="f-status">
        <option value="">All</option>
        <option value="ok">ok</option>
        <option value="partial">partial</option>
        <option value="failed">failed</option>
      </select>
    </label>
    <button id="apply-btn">Apply</button>`;
  document.getElementById("apply-btn").addEventListener("click", loadRuns);
}

let currentOffset = 0;
const PAGE_SIZE = 50;

async function loadRuns() {
  const start = document.getElementById("f-start")?.value;
  const end = document.getElementById("f-end")?.value;
  const filename = document.getElementById("f-filename")?.value || "";
  const status = document.getElementById("f-status")?.value || "";

  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: currentOffset });
  if (start) params.set("start_ts", dateInputToEpoch(start));
  if (end) params.set("end_ts", dateInputToEpoch(end) + 86399);
  if (filename) params.set("filename", filename);
  if (status) params.set("status", status);

  const resp = await fetch(`/api/imports/runs?${params}`);
  const body = await resp.json();
  renderRunsTable(body.runs, body.total);
}

function renderRunsTable(runs, total) {
  const container = document.getElementById("runs-table");
  if (!runs.length) {
    container.innerHTML = "<p>No import ticks found.</p>";
    return;
  }
  const rows = runs.map((r) => {
    const started = new Date(r.started_at * 1000).toLocaleString();
    const duration = r.finished_at && r.started_at
      ? ((r.finished_at - r.started_at) * 1000).toFixed(0) + " ms"
      : "—";
    const cursor = `${r.cursor_before} → ${r.cursor_after}`;
    return `<tr style="cursor:pointer" data-tid="${r.tick_id}">
      <td>${r.tick_id}</td>
      <td>${escHtml(r.filename)}</td>
      <td>${started}</td>
      <td>${duration}</td>
      <td>${escHtml(r.status)}</td>
      <td>${r.rows_inserted}</td>
      <td>${r.rows_skipped_duplicate}</td>
      <td>${r.rows_rejected}</td>
      <td>${escHtml(cursor)}</td>
    </tr>`;
  });
  container.innerHTML = `
    <p style="color:#666">${total} total</p>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>File</th><th>Started</th><th>Duration</th>
          <th>Status</th><th>Inserted</th><th>Dups</th><th>Rejected</th><th>Cursor</th>
        </tr>
      </thead>
      <tbody>${rows.join("")}</tbody>
    </table>
    <div class="pagination">
      <button id="prev-btn" ${currentOffset === 0 ? "disabled" : ""}>Previous</button>
      <span>Showing ${currentOffset + 1}–${Math.min(currentOffset + PAGE_SIZE, total)} of ${total}</span>
      <button id="next-btn" ${currentOffset + PAGE_SIZE >= total ? "disabled" : ""}>Next</button>
    </div>`;

  container.querySelectorAll("tbody tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      window.location.href = `/imports/${tr.dataset.tid}`;
    });
  });
  document.getElementById("prev-btn")?.addEventListener("click", () => {
    currentOffset = Math.max(0, currentOffset - PAGE_SIZE);
    loadRuns();
  });
  document.getElementById("next-btn")?.addEventListener("click", () => {
    currentOffset += PAGE_SIZE;
    loadRuns();
  });
}

async function onScanNow() {
  const btn = document.getElementById("scan-btn");
  btn.textContent = "Scanning…";
  btn.disabled = true;
  try {
    const resp = await fetch("/api/imports/scan", { method: "POST" });
    const body = await resp.json();
    alert(`Scan complete: ${body.ticked} file(s) ticked.`);
    await renderCursorsBand();
    await loadRuns();
  } finally {
    btn.textContent = "Scan Now";
    btn.disabled = false;
  }
}

// ------------------------------------------------------------------ //
// Detail page                                                         //
// ------------------------------------------------------------------ //

async function initDetail() {
  const el = document.getElementById("tick-detail");
  const tickId = parseInt(el.dataset.tickId, 10);

  const resp = await fetch(`/api/imports/runs/${tickId}`);
  if (!resp.ok) {
    el.textContent = "Tick not found.";
    return;
  }
  const tick = await resp.json();
  renderTickDetail(tick);
  renderRejectsTable(tick.rejects || []);
  await renderRollbackSection(tickId, tick);
}

function renderTickDetail(tick) {
  const el = document.getElementById("tick-detail");
  const started = new Date(tick.started_at * 1000).toLocaleString();
  const finished = tick.finished_at ? new Date(tick.finished_at * 1000).toLocaleString() : "—";
  const duration = tick.finished_at
    ? ((tick.finished_at - tick.started_at) * 1000).toFixed(0) + " ms"
    : "—";
  el.innerHTML = `
    <dl class="detail-header">
      <dt>File</dt><dd>${escHtml(tick.filename)}</dd>
      <dt>Status</dt><dd>${escHtml(tick.status)}</dd>
      <dt>Started</dt><dd>${started}</dd>
      <dt>Finished</dt><dd>${finished}</dd>
      <dt>Duration</dt><dd>${duration}</dd>
      <dt>Inserted</dt><dd>${tick.rows_inserted}</dd>
      <dt>Duplicates</dt><dd>${tick.rows_skipped_duplicate}</dd>
      <dt>Rejected</dt><dd>${tick.rows_rejected}</dd>
      <dt>Cursor Before</dt><dd>${tick.cursor_before}</dd>
      <dt>Cursor After</dt><dd>${tick.cursor_after}</dd>
    </dl>`;
}

function renderRejectsTable(rejects) {
  const el = document.getElementById("rejects-table");
  if (!rejects.length) {
    el.innerHTML = "<p>No rejected rows.</p>";
    return;
  }
  const rows = rejects.map((r) =>
    `<tr>
      <td>${r.line_number}</td>
      <td>${escHtml(r.reason)}</td>
      <td><code>${escHtml(r.raw_line)}</code></td>
    </tr>`
  );
  el.innerHTML = `
    <h2>Rejected Rows (${rejects.length})</h2>
    <table>
      <thead><tr><th>Line</th><th>Reason</th><th>Raw</th></tr></thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;
}

async function renderRollbackSection(tickId, tick) {
  const el = document.getElementById("rollback-section");
  const resp = await fetch(`/api/imports/runs/${tickId}/executions`);
  if (!resp.ok) {
    el.innerHTML = "";
    return;
  }
  const { execution_ids: ids } = await resp.json();
  if (!ids.length) {
    el.innerHTML = "<p>No executions found for this tick (already rolled back or nothing was inserted).</p>";
    return;
  }
  el.innerHTML = `
    <h2>Rollback</h2>
    <p>This tick inserted <strong>${ids.length}</strong> execution(s). Rolling back deletes them.</p>
    <button class="danger" id="rollback-btn">Roll Back This Tick</button>`;
  document.getElementById("rollback-btn").addEventListener("click", async () => {
    const preview = ids.slice(0, 5).join(", ") + (ids.length > 5 ? ` … +${ids.length - 5} more` : "");
    if (!confirm(`Delete ${ids.length} execution(s)?\n\n${preview}`)) return;
    const r = await fetch("/api/executions/rollback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ execution_ids: ids }),
    });
    const body = await r.json();
    alert(`Rolled back ${body.deleted} execution(s).`);
    window.location.href = "/imports";
  });
}

// ------------------------------------------------------------------ //
// Helpers                                                             //
// ------------------------------------------------------------------ //

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function epochToDateInput(ts) {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

function dateInputToEpoch(s) {
  return Math.floor(new Date(s).getTime() / 1000);
}
```

- [ ] **Step 2: Verify the page renders in the browser**

Start the app with `docker compose up -d --build` and navigate to `http://localhost:8000/imports`. Verify:
- Page loads without JS errors
- Cursor band shows (or "No active inbox files")
- Scan Now button is present
- Filter controls are present

Navigate to `/imports/1` (or any tick_id from a real run). Verify detail renders.

- [ ] **Step 3: Commit**

```bash
git add static/js/imports.js
git commit -m "feat(plan17): imports list and detail page JS"
```

---

## Task 8: Validation page JS

**Files:**
- Create: `static/js/validation.js`

- [ ] **Step 1: Create `static/js/validation.js`**

```javascript
// validation.js — /validation page

initValidation();

async function initValidation() {
  renderFilters();
  await loadIssues();
}

function renderFilters() {
  const bar = document.getElementById("filters-bar");
  if (!bar) return;
  bar.innerHTML = `
    <label>Status
      <select id="f-status">
        <option value="open">Open</option>
        <option value="resolved">Resolved</option>
        <option value="ignored">Ignored</option>
        <option value="all">All</option>
      </select>
    </label>
    <label>Severity
      <select id="f-severity">
        <option value="">All</option>
        <option value="high">High</option>
        <option value="medium">Medium</option>
        <option value="low">Low</option>
      </select>
    </label>
    <label>Account<input type="text" id="f-account" placeholder="account name"></label>
    <label>Instrument<input type="text" id="f-instrument" placeholder="e.g. MNQ"></label>
    <button id="apply-btn">Apply</button>`;
  document.getElementById("apply-btn").addEventListener("click", loadIssues);
  document.getElementById("f-status").addEventListener("change", loadIssues);
}

async function loadIssues() {
  const status = document.getElementById("f-status")?.value || "open";
  const severity = document.getElementById("f-severity")?.value || "";
  const account = document.getElementById("f-account")?.value || "";
  const instrument = document.getElementById("f-instrument")?.value || "";

  const params = new URLSearchParams({ status });
  if (severity) params.set("severity", severity);
  if (account) params.set("account", account);
  if (instrument) params.set("instrument", instrument);

  const resp = await fetch(`/api/integrity-issues?${params}`);
  const { issues } = await resp.json();
  renderIssues(issues, status);
}

function renderIssues(issues, status) {
  const el = document.getElementById("issues-table");
  if (!issues.length) {
    el.innerHTML = `<p>No ${status} integrity issues.</p>`;
    return;
  }
  const rows = issues.map((i) => {
    const age = Math.floor((Date.now() / 1000 - i.detected_at) / 3600);
    const detected = new Date(i.detected_at * 1000).toLocaleString();
    const execLink = i.execution_id
      ? `<a href="/positions?q=${encodeURIComponent(i.execution_id)}">${escHtml(i.execution_id)}</a>`
      : "—";
    const noteCell = i.resolution_note
      ? `<span style="color:#666;font-style:italic">${escHtml(i.resolution_note)}</span>`
      : i.ignore_note
      ? `<span style="color:#666;font-style:italic">${escHtml(i.ignore_note)}</span>`
      : "";
    const actionCell = i.resolved_at || i.ignored
      ? noteCell
      : `<button class="resolve-btn" data-id="${i.issue_id}">Resolve</button>
         <button class="ignore-btn" data-id="${i.issue_id}">Ignore</button>`;

    const sevColor = i.severity === "high" ? "#b00020" : i.severity === "medium" ? "#c07000" : "#555";
    return `<tr>
      <td style="color:${sevColor};font-weight:600">${escHtml(i.severity)}</td>
      <td>${escHtml(i.type)}</td>
      <td>${escHtml(i.account)}</td>
      <td>${escHtml(i.instrument)}</td>
      <td>${execLink}</td>
      <td>${escHtml(i.description)}</td>
      <td>${detected}</td>
      <td>${age}h</td>
      <td>${actionCell}</td>
    </tr>`;
  });
  el.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Severity</th><th>Type</th><th>Account</th><th>Instrument</th>
          <th>Execution</th><th>Description</th><th>Detected</th><th>Age</th><th>Action</th>
        </tr>
      </thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;

  el.querySelectorAll(".resolve-btn").forEach((btn) => {
    btn.addEventListener("click", () => resolveIssue(btn.dataset.id));
  });
  el.querySelectorAll(".ignore-btn").forEach((btn) => {
    btn.addEventListener("click", () => ignoreIssue(btn.dataset.id));
  });
}

async function resolveIssue(id) {
  const note = prompt("Resolution note (optional):") ?? "";
  const resp = await fetch(`/api/integrity-issues/${id}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note: note || null }),
  });
  if (resp.ok) await loadIssues();
  else alert("Failed to resolve issue.");
}

async function ignoreIssue(id) {
  const note = prompt("Why are you ignoring this issue? (required):");
  if (!note) return;
  const resp = await fetch(`/api/integrity-issues/${id}/ignore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  if (resp.ok) await loadIssues();
  else alert("Failed to ignore issue.");
}

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
```

- [ ] **Step 2: Browser verify**

Navigate to `http://localhost:8000/validation`. Verify:
- Filter controls render
- "No open integrity issues" message shows (or issues if any exist)
- Status dropdown works (switch to "all" shows all rows including resolved)
- Resolve and Ignore buttons appear for open issues

- [ ] **Step 3: Commit**

```bash
git add static/js/validation.js
git commit -m "feat(plan17): validation page JS"
```

---

## Task 9: Data health page JS

**Files:**
- Create: `static/js/data_health.js`

- [ ] **Step 1: Create `static/js/data_health.js`**

```javascript
// data_health.js — /data-health page

initDataHealth();

async function initDataHealth() {
  await renderSourcesBand();
  await renderMatrix();
}

async function renderSourcesBand() {
  const el = document.getElementById("sources-band");
  if (!el) return;
  const resp = await fetch("/api/ohlc/sources");
  const { sources } = await resp.json();
  const hasOpen = sources.some((s) => s.state === "open");
  let banner = "";
  if (hasOpen) {
    const openSources = sources.filter((s) => s.state === "open");
    banner = openSources.map((s) =>
      `<div class="alert-banner">
        OHLC source <strong>${escHtml(s.name)}</strong> is currently unavailable
        (since ${s.opened_at ? new Date(s.opened_at * 1000).toLocaleString() : "unknown"},
        reason: ${escHtml(s.last_error ?? "unknown")}).
        Falling back to next available source. The rest of the app continues to work normally.
      </div>`
    ).join("");
  }
  const rows = sources.map((s) => {
    const stateColor = s.state === "closed" ? "#0a7f0a" : s.state === "open" ? "#b00020" : "#c07000";
    const lastSuccess = s.last_success_at ? new Date(s.last_success_at * 1000).toLocaleString() : "—";
    const lastFail = s.last_failure_at ? new Date(s.last_failure_at * 1000).toLocaleString() : "—";
    const nextRetry = s.state === "open" && s.opened_at
      ? new Date((s.opened_at + 600) * 1000).toLocaleString()
      : "—";
    return `<tr>
      <td>${escHtml(s.name)}</td>
      <td style="color:${stateColor};font-weight:600">${escHtml(s.state)}</td>
      <td>${lastSuccess}</td>
      <td>${lastFail}</td>
      <td>${escHtml(s.last_error ?? "—")}</td>
      <td>${nextRetry}</td>
    </tr>`;
  });
  el.innerHTML = `
    ${banner}
    <h3 style="margin-top:0">OHLC Sources</h3>
    <table>
      <thead><tr><th>Source</th><th>State</th><th>Last Success</th><th>Last Failure</th><th>Last Error</th><th>Next Retry</th></tr></thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;
}

async function renderMatrix() {
  const el = document.getElementById("completeness-matrix");
  el.innerHTML = "<p>Loading…</p>";

  const resp = await fetch("/api/data-health/completeness");
  const body = await resp.json();

  if (!body.instruments.length) {
    el.innerHTML = "<p>No instruments with executions in the last 90 days.</p>";
    return;
  }

  const statusStyle = {
    complete: "background:#d4edda;color:#155724",
    partial: "background:#fff3cd;color:#856404",
    missing: "background:#f8d7da;color:#721c24",
    session_closed: "background:#e2e3e5;color:#383d41",
  };

  const headerCells = body.timeframes.map((tf) => `<th>${tf}</th>`).join("");
  const dataRows = body.instruments.map((inst) => {
    const cells = body.timeframes.map((tf) => {
      const status = body.cells[inst]?.[tf] ?? "missing";
      const style = statusStyle[status] ?? "";
      return `<td style="${style};text-align:center;cursor:pointer;padding:6px 10px"
               data-inst="${inst}" data-tf="${tf}" class="cell-btn"
               title="${status}">${status}</td>`;
    }).join("");
    return `<tr><td><strong>${escHtml(inst)}</strong></td>${cells}</tr>`;
  }).join("");

  el.innerHTML = `
    <div style="margin-bottom:8px">
      <label>Lookback days: <input type="number" id="days-input" value="${body.days}" min="1" max="365" style="width:60px"></label>
      <button id="reload-btn">Reload</button>
    </div>
    <table>
      <thead><tr><th>Instrument</th>${headerCells}</tr></thead>
      <tbody>${dataRows}</tbody>
    </table>`;

  el.querySelectorAll(".cell-btn").forEach((btn) => {
    btn.addEventListener("click", () => openDetailPanel(btn.dataset.inst, btn.dataset.tf, body.window_start, body.window_end));
  });
  document.getElementById("reload-btn").addEventListener("click", async () => {
    const days = document.getElementById("days-input").value;
    const r = await fetch(`/api/data-health/completeness?days=${days}`);
    // Re-render with new data
    const nb = await r.json();
    // Simplest approach: reload whole matrix
    await renderMatrix();
  });
}

async function openDetailPanel(instrument, timeframe, start, end) {
  const panel = document.getElementById("detail-panel");
  panel.style.display = "block";
  panel.innerHTML = `<h3>${escHtml(instrument)} / ${escHtml(timeframe)} — gaps</h3><p>Loading…</p>`;

  const resp = await fetch(`/api/data-health/missing/${instrument}/${timeframe}?start=${start}&end=${end}`);
  const body = await resp.json();

  if (!body.gaps.length) {
    panel.innerHTML = `<h3>${escHtml(instrument)} / ${escHtml(timeframe)}</h3>
      <p>No gaps in this window. ${body.present_bars} of ${body.expected_slots} expected bars present.</p>
      <button id="close-panel">Close</button>`;
  } else {
    const gapRows = body.gaps.map((g) =>
      `<tr>
        <td>${new Date(g.start * 1000).toLocaleString()}</td>
        <td>${new Date(g.end * 1000).toLocaleString()}</td>
        <td>
          <button class="fetch-gap-btn"
            data-inst="${instrument}" data-tf="${timeframe}"
            data-start="${g.start}" data-end="${g.end}">Fetch Missing</button>
        </td>
      </tr>`
    ).join("");
    panel.innerHTML = `
      <h3>${escHtml(instrument)} / ${escHtml(timeframe)}</h3>
      <p>${body.present_bars} of ${body.expected_slots} expected bars present. ${body.gaps.length} gap(s):</p>
      <table>
        <thead><tr><th>Gap Start</th><th>Gap End</th><th>Action</th></tr></thead>
        <tbody>${gapRows}</tbody>
      </table>
      <button id="close-panel">Close</button>`;

    panel.querySelectorAll(".fetch-gap-btn").forEach((btn) => {
      btn.addEventListener("click", () => fetchGap(btn.dataset.inst, btn.dataset.tf, btn.dataset.start, btn.dataset.end, btn));
    });
  }
  document.getElementById("close-panel")?.addEventListener("click", () => {
    panel.style.display = "none";
  });
}

async function fetchGap(instrument, timeframe, start, end, btn) {
  btn.textContent = "Fetching…";
  btn.disabled = true;
  const resp = await fetch(`/api/chart/${instrument}/fetch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ timeframe, start: parseInt(start), end: parseInt(end) }),
  });
  const body = await resp.json();
  if (resp.status === 202) {
    btn.textContent = `Job ${body.job_id} started`;
    pollJob(body.job_id, btn);
  } else {
    btn.textContent = "Error";
    btn.disabled = false;
  }
}

async function pollJob(jobId, btn) {
  const resp = await fetch(`/api/ohlc/jobs/${jobId}`);
  const body = await resp.json();
  if (body.state === "done") {
    btn.textContent = "Done — reload to see changes";
  } else if (body.state === "error") {
    btn.textContent = "Fetch failed";
    btn.disabled = false;
  } else {
    setTimeout(() => pollJob(jobId, btn), 1000);
  }
}

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
```

- [ ] **Step 2: Browser verify**

Navigate to `http://localhost:8000/data-health`. Verify:
- Source status band renders
- Matrix shows instruments (or "No instruments" if none)
- Color codes are visible
- Clicking a cell opens the detail panel
- "Fetch Missing" button is present on gap rows

- [ ] **Step 3: Commit**

```bash
git add static/js/data_health.js
git commit -m "feat(plan17): data health matrix page JS"
```

---

## Task 10: System health page JS

**Files:**
- Create: `static/js/system_health.js`

- [ ] **Step 1: Create `static/js/system_health.js`**

```javascript
// system_health.js — /system/health page

let autoRefreshInterval = null;

initSystemHealth();

async function initSystemHealth() {
  await renderHealthz();
  await renderHealth();
  setupAutoRefresh();
}

async function renderHealthz() {
  const el = document.getElementById("healthz-section");
  if (!el) return;
  el.innerHTML = `
    <button id="healthz-btn">Run Healthz Check</button>
    <span id="healthz-result" style="margin-left:12px"></span>`;
  document.getElementById("healthz-btn").addEventListener("click", async () => {
    const result = document.getElementById("healthz-result");
    result.textContent = "Checking…";
    const resp = await fetch("/healthz");
    const body = await resp.json();
    const ok = resp.status === 200;
    result.style.color = ok ? "#0a7f0a" : "#b00020";
    result.textContent = ok
      ? "✓ Healthy"
      : `✗ Unhealthy: ${Object.entries(body).filter(([, v]) => !v).map(([k]) => k).join(", ")}`;
  });
}

async function renderHealth() {
  const resp = await fetch("/api/system/health");
  const body = await resp.json();
  renderJobs(body.jobs);
  renderPool(body.pool);
  renderWatchdog(body.watchdog);
  renderUptime(body);
}

function renderJobs(jobs) {
  const el = document.getElementById("jobs-table");
  if (!jobs.length) {
    el.innerHTML = "<p>No scheduled jobs.</p>";
    return;
  }
  const rows = jobs.map((j) => {
    const next = j.next_run_time ? new Date(j.next_run_time * 1000).toLocaleString() : "—";
    const last = j.last_run_at ? new Date(j.last_run_at * 1000).toLocaleString() : "—";
    const statusColor = j.last_run_status === "error" ? "#b00020" : j.last_run_status === "success" ? "#0a7f0a" : "#888";
    const avgMs = j.avg_duration_ms != null ? `${j.avg_duration_ms} ms` : "—";
    return `<tr>
      <td>${escHtml(j.job_id)}</td>
      <td>${escHtml(j.trigger)}</td>
      <td>${last}</td>
      <td style="color:${statusColor}">${j.last_run_status ?? "—"}</td>
      <td>${next}</td>
      <td>${avgMs}</td>
      <td><button class="run-now-btn" data-job-id="${j.job_id}">Run Now</button></td>
    </tr>`;
  });
  el.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Job ID</th><th>Trigger</th><th>Last Run</th><th>Status</th>
          <th>Next Run</th><th>Avg Duration</th><th>Action</th>
        </tr>
      </thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;

  el.querySelectorAll(".run-now-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.textContent = "Running…";
      btn.disabled = true;
      const resp = await fetch(`/api/system/run-job/${btn.dataset.jobId}`, { method: "POST" });
      if (resp.ok) {
        btn.textContent = "Done";
        setTimeout(() => renderHealth(), 500);
      } else {
        btn.textContent = "Error";
        btn.disabled = false;
      }
    });
  });
}

function renderPool(pool) {
  const el = document.getElementById("pool-section");
  if (!el) return;
  el.innerHTML = `
    <dl class="detail-header">
      <dt>Max Workers</dt><dd>${pool.max_workers}</dd>
      <dt>Spawned Threads</dt><dd>${pool.spawned_threads ?? "—"}</dd>
      <dt>Pending Queue</dt><dd>${pool.pending_queue ?? "—"}</dd>
    </dl>`;
}

function renderWatchdog(watchdog) {
  const el = document.getElementById("watchdog-section");
  if (!el) return;
  const aliveColor = watchdog.alive ? "#0a7f0a" : "#b00020";
  el.innerHTML = `
    <dl class="detail-header">
      <dt>Status</dt><dd style="color:${aliveColor}">${watchdog.alive ? "Alive" : "Dead"}</dd>
      <dt>Watching</dt><dd>${escHtml(watchdog.path)}</dd>
    </dl>`;
}

function renderUptime(body) {
  const el = document.getElementById("uptime-section");
  if (!el) return;
  const startedAt = body.started_at ? new Date(body.started_at * 1000).toLocaleString() : "—";
  const uptime = formatDuration(body.uptime_seconds ?? 0);
  el.innerHTML = `
    <dl class="detail-header">
      <dt>Process Started</dt><dd>${startedAt}</dd>
      <dt>Uptime</dt><dd>${uptime}</dd>
      <dt>Python Version</dt><dd>${escHtml(body.python_version ?? "—")}</dd>
    </dl>`;
}

function setupAutoRefresh() {
  const container = document.querySelector("h1");
  if (!container) return;
  const toggle = document.createElement("label");
  toggle.style.cssText = "margin-left:16px;font-size:14px;font-weight:normal;cursor:pointer";
  toggle.innerHTML = `<input type="checkbox" id="auto-refresh"> Auto-refresh (10s)`;
  container.after(toggle);
  document.getElementById("auto-refresh").addEventListener("change", (e) => {
    if (e.target.checked) {
      autoRefreshInterval = setInterval(renderHealth, 10000);
    } else {
      clearInterval(autoRefreshInterval);
      autoRefreshInterval = null;
    }
  });
}

function formatDuration(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h && `${h}h`, m && `${m}m`, `${s}s`].filter(Boolean).join(" ");
}

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
```

- [ ] **Step 2: Browser verify**

Navigate to `http://localhost:8000/system/health`. Verify:
- "Run Healthz Check" button works (shows green/red)
- APScheduler jobs table renders with all 5 jobs (heartbeat, import_safety_sweep, archive_completed_sessions, ohlc_refresh_recent, ohlc_refresh_week)
- Thread pool section shows max_workers = 4
- Watchdog section shows "Alive"
- Uptime counter shows elapsed time
- "Run Now" button for heartbeat runs immediately (last_run_at updates after 0.5s refresh)
- Auto-refresh toggle polls every 10s

- [ ] **Step 3: Commit**

```bash
git add static/js/system_health.js
git commit -m "feat(plan17): system health page JS"
```

---

## Task 11: Update README and run full test suite

**Files:**
- Modify: `docs/rebuild-spec/00-README.md`

- [ ] **Step 1: Run full test suite**

```
pytest -q
```

Expected: all PASS (no regressions)

- [ ] **Step 2: Update `docs/rebuild-spec/00-README.md`**

In the Implementation Progress table, update the plan 16 and 17 rows.

Find:
```
| 16 — Settings & Custom Fields | `instruments.json` registry, `chart_defaults`, `custom_fields` + values, `/settings/*` pages | ⏳ |
| 17 — Monitoring | `/imports`, `/validation`, `/data-health`, `/system/health` pages and APIs | ⏳ |
```

Replace with:
```
| [16 — Settings & Custom Fields](../superpowers/plans/2026-04-13-16-settings-instruments.md) | `instruments.json` registry, `chart_defaults`, `custom_fields` + values, `/settings/*` pages | ✅ **Complete** (2026-04-13) |
| [17 — Monitoring](../superpowers/plans/2026-04-14-17-import-monitoring.md) | `/imports`, `/validation`, `/data-health`, `/system/health` pages and APIs | ✅ **Complete** (2026-04-14) |
```

- [ ] **Step 3: Final commit**

```bash
git add docs/rebuild-spec/00-README.md
git commit -m "docs: mark plans 16 and 17 complete"
```

---

## Self-Review — Spec Coverage

| Spec requirement | Task |
|---|---|
| `/imports` paginated list, 50/page, newest first | Task 1 + Task 7 |
| Tick row: id, filename, started_at, duration, status, counts, cursor | Task 7 |
| Default filter last 7 days, filterable by filename, status, date range | Task 1 + Task 7 |
| `/imports/{tick_id}` detail with rejects | Task 2 + Task 7 |
| Cursor band (active inbox files + byte offsets) | Task 7 |
| Rollback action with confirm dialog | Task 2 + Task 7 |
| "Scan now" button | Task 7 |
| `/validation` open issues sorted by severity | Task 3 + Task 8 |
| Filter by status/severity/account/instrument | Task 3 + Task 8 |
| Resolve + Ignore actions with notes | Task 8 |
| Auto-resolve banner | Task 6 (template inline text) |
| No "run validation now" button | Confirmed absent |
| `/data-health` matrix, active instruments × 6 timeframes | Task 5 + Task 9 |
| Status: complete/partial/missing/session_closed | Task 5 |
| Color codes | Task 9 |
| Click cell → gap detail + "Fetch missing" button | Task 9 |
| Per-source status band | Task 9 |
| Open-source banner | Task 9 |
| No quota widget | Confirmed absent |
| `/system/health` APScheduler jobs table | Task 4 + Task 10 |
| Thread pool section | Task 4 + Task 10 |
| Watchdog observer section | Task 4 + Task 10 |
| Uptime section | Task 4 + Task 10 |
| "Run Now" per job | Task 4 + Task 10 |
| "Healthz check" button | Task 10 |
| No Redis/Celery rows | Confirmed absent |
| Auto-refresh toggle | Task 10 |
| `GET /api/data-health/completeness` | Task 5 |
| `GET /api/data-health/missing/{instrument}/{timeframe}` | Task 5 |
| `GET /api/system/health` | Task 5 |
| `POST /api/system/run-job/{job_id}` | Task 5 |
| All existing API endpoints reused (imports, ohlc, integrity, healthz) | Reused — no duplication |

**Fragmentation hazard check:**
- FH1: Four pages exactly — ✓ `/imports`, `/validation`, `/data-health`, `/system/health`
- FH2: Only `BackgroundServices` — ✓ no parallel runtime
- FH3: No alerts table — ✓ banners computed live
- FH4: One fetch action — ✓ reuses `POST /api/chart/{instrument}/fetch`
- FH5: One validation UI — ✓ single `/validation` page from `integrity_issues`
- FH6: No quota widgets — ✓ only circuit breaker state shown
- FH7: No external service health checks — ✓ only in-process state
