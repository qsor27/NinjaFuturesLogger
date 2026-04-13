import threading
import time
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from db import connect
from logging_config import get_logger
from models.execution import Execution, RejectRecord, TickResult
from services.csv_parser import ParseError, parse_execution_row
from services.import_db import (
    bulk_insert_executions,
    delete_cursor,
    delete_executions,
    get_cursor,
    insert_rejects,
    record_run,
    save_cursor,
)

log = get_logger("import.pipeline")

PostTickHook = Callable[[TickResult, list[Execution], set[tuple[str, str]]], None]


class ImportPipeline:
    """Single entry point for all data. One instance per process."""

    def __init__(
        self,
        *,
        db_path: Path | str,
        trader_tz: ZoneInfo,
        post_tick_hooks: list[PostTickHook] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.trader_tz = trader_tz
        self.post_tick_hooks: list[PostTickHook] = list(post_tick_hooks or [])
        self._path_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def ingest_tick(self, path: Path) -> TickResult:
        """Read any new bytes from `path`, parse complete lines, insert executions."""
        path = Path(path)
        filename = path.name
        started_at = int(time.time())

        with self._lock_for(filename):
            tick_result, parsed = self._run_tick(path, filename, started_at)

        affected = {(e.account, e.instrument) for e in parsed} if parsed else set()
        self._fire_hooks(tick_result, parsed, affected)
        return tick_result

    def scan_inbox(self, inbox_dir: Path | str) -> list[TickResult]:
        results: list[TickResult] = []
        for p in sorted(Path(inbox_dir).glob("NinjaTrader_Executions_*.csv")):
            try:
                results.append(self.ingest_tick(p))
            except Exception as e:
                log.exception("scan_inbox: tick failed", extra={"path": str(p)})
                results.append(
                    TickResult(
                        filename=p.name,
                        status="failed",
                        lines_read=0,
                        rows_parsed=0,
                        rows_inserted=0,
                        rows_skipped_duplicate=0,
                        rows_rejected=0,
                        cursor_before=0,
                        cursor_after=0,
                        tick_id=None,
                        error=str(e),
                    )
                )
        return results

    def rollback(self, nt_execution_ids: Sequence[str]) -> int:
        conn = connect(self.db_path)
        try:
            conn.execute("BEGIN")
            try:
                deleted = delete_executions(conn, nt_execution_ids)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return deleted

    def archive_completed_sessions(
        self,
        *,
        inbox_dir: Path | str,
        archive_dir: Path | str,
        current_trade_date: date,
    ) -> list[Path]:
        inbox = Path(inbox_dir)
        archive = Path(archive_dir)
        moved: list[Path] = []
        if not isinstance(current_trade_date, date):
            raise TypeError("current_trade_date must be a date")
        for path in sorted(inbox.glob("NinjaTrader_Executions_*.csv")):
            file_date = _parse_date_from_filename(path.name)
            if file_date is None:
                continue
            if file_date >= current_trade_date:
                continue
            self.ingest_tick(path)
            dest_dir = archive / file_date.isoformat()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / path.name
            path.rename(dest)
            conn = connect(self.db_path)
            try:
                conn.execute("BEGIN")
                try:
                    delete_cursor(conn, path.name)
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            finally:
                conn.close()
            moved.append(dest)
            log.info("archived", extra={"csv_name": path.name, "dest": str(dest)})
        return moved

    def _lock_for(self, filename: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._path_locks.get(filename)
            if lock is None:
                lock = threading.Lock()
                self._path_locks[filename] = lock
            return lock

    def _run_tick(
        self,
        path: Path,
        filename: str,
        started_at: int,
    ) -> tuple[TickResult, list[Execution]]:
        conn = connect(self.db_path)
        try:
            cursor = get_cursor(conn, filename) or 0
            size = path.stat().st_size
            mtime = int(path.stat().st_mtime)

            if size < cursor:
                log.warning(
                    "file shrank, resetting cursor",
                    extra={"csv_name": filename, "old": cursor, "new": size},
                )
                cursor = 0

            if size == cursor:
                return self._finish(
                    conn,
                    filename,
                    started_at,
                    cursor,
                    cursor,
                    lines=[],
                    parsed=[],
                    rejects=[],
                    status="ok",
                    mtime=mtime,
                )

            with open(path, "rb") as f:
                f.seek(cursor)
                chunk = f.read(size - cursor)

            last_nl = chunk.rfind(b"\n")
            if last_nl == -1:
                return self._finish(
                    conn,
                    filename,
                    started_at,
                    cursor,
                    cursor,
                    lines=[],
                    parsed=[],
                    rejects=[],
                    status="partial",
                    mtime=mtime,
                )

            complete = chunk[: last_nl + 1]
            new_cursor = cursor + len(complete)
            try:
                text = complete.decode("utf-8")
            except UnicodeDecodeError as e:
                log.exception("decode error", extra={"csv_name": filename})
                conn.execute("BEGIN")
                try:
                    tick_id = record_run(
                        conn,
                        filename=filename,
                        started_at=started_at,
                        finished_at=int(time.time()),
                        cursor_before=cursor,
                        cursor_after=new_cursor,
                        lines_read=0,
                        rows_parsed=0,
                        rows_inserted=0,
                        rows_skipped_duplicate=0,
                        rows_rejected=0,
                        status="failed",
                        error=f"decode: {e}",
                    )
                    save_cursor(conn, filename, byte_offset=new_cursor, file_mtime=mtime)
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                return (
                    TickResult(
                        filename=filename,
                        status="failed",
                        lines_read=0,
                        rows_parsed=0,
                        rows_inserted=0,
                        rows_skipped_duplicate=0,
                        rows_rejected=0,
                        cursor_before=cursor,
                        cursor_after=new_cursor,
                        tick_id=tick_id,
                        error=f"decode: {e}",
                    ),
                    [],
                )
            lines = text.splitlines()

            if cursor == 0 and lines and lines[0].startswith("Instrument"):
                lines = lines[1:]

            parsed: list[Execution] = []
            rejects: list[RejectRecord] = []
            imported_at = int(time.time())
            for i, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    parsed.append(
                        parse_execution_row(
                            line,
                            source_filename=filename,
                            trader_tz=self.trader_tz,
                            imported_at=imported_at,
                        )
                    )
                except ParseError as e:
                    rejects.append(
                        RejectRecord(
                            line_number=i,
                            raw_line=line,
                            reason=str(e),
                        )
                    )

            return self._finish(
                conn,
                filename,
                started_at,
                cursor,
                new_cursor,
                lines=lines,
                parsed=parsed,
                rejects=rejects,
                status="ok",
                mtime=mtime,
            )
        finally:
            conn.close()

    def _finish(
        self,
        conn,
        filename: str,
        started_at: int,
        cursor_before: int,
        cursor_after: int,
        *,
        lines: list[str],
        parsed: list[Execution],
        rejects: list[RejectRecord],
        status: str,
        mtime: int,
    ) -> tuple[TickResult, list[Execution]]:
        conn.execute("BEGIN")
        try:
            inserted, skipped = bulk_insert_executions(conn, parsed)
            tick_id = record_run(
                conn,
                filename=filename,
                started_at=started_at,
                finished_at=int(time.time()),
                cursor_before=cursor_before,
                cursor_after=cursor_after,
                lines_read=len(lines),
                rows_parsed=len(parsed),
                rows_inserted=inserted,
                rows_skipped_duplicate=skipped,
                rows_rejected=len(rejects),
                status=status,
                error=None,
            )
            if rejects:
                insert_rejects(conn, tick_id, rejects)
            save_cursor(conn, filename, byte_offset=cursor_after, file_mtime=mtime)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return (
            TickResult(
                filename=filename,
                status=status,
                lines_read=len(lines),
                rows_parsed=len(parsed),
                rows_inserted=inserted,
                rows_skipped_duplicate=skipped,
                rows_rejected=len(rejects),
                cursor_before=cursor_before,
                cursor_after=cursor_after,
                tick_id=tick_id,
                error=None,
            ),
            parsed,
        )

    def _fire_hooks(
        self,
        result: TickResult,
        parsed: list[Execution],
        affected: set[tuple[str, str]],
    ) -> None:
        for hook in self.post_tick_hooks:
            try:
                hook(result, parsed, affected)
            except Exception:
                log.exception("post-tick hook failed", extra={"hook": repr(hook)})


def _parse_date_from_filename(name: str) -> date | None:
    prefix = "NinjaTrader_Executions_"
    suffix = ".csv"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    core = name[len(prefix) : -len(suffix)]
    if len(core) != 8 or not core.isdigit():
        return None
    try:
        return date(int(core[:4]), int(core[4:6]), int(core[6:8]))
    except ValueError:
        return None
