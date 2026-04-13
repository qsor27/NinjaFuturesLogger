import sqlite3
import time
from collections.abc import Iterable, Sequence

from models.execution import Execution, RejectRecord

_INSERT_EXECUTION_SQL = (
    "INSERT INTO executions ("
    " nt_execution_id, account, instrument, timestamp, side,"
    " original_action, quantity, price, commission, entry_exit,"
    " position_after, source_order_id, source_filename, imported_at"
    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING"
)


def get_cursor(conn: sqlite3.Connection, filename: str) -> int | None:
    row = conn.execute(
        "SELECT byte_offset FROM import_cursors WHERE filename = ?",
        (filename,),
    ).fetchone()
    return int(row[0]) if row is not None else None


def save_cursor(
    conn: sqlite3.Connection,
    filename: str,
    *,
    byte_offset: int,
    file_mtime: int,
) -> None:
    conn.execute(
        "INSERT INTO import_cursors (filename, byte_offset, last_tick_at, last_modified) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(filename) DO UPDATE SET "
        " byte_offset = excluded.byte_offset,"
        " last_tick_at = excluded.last_tick_at,"
        " last_modified = excluded.last_modified",
        (filename, byte_offset, int(time.time()), file_mtime),
    )


def delete_cursor(conn: sqlite3.Connection, filename: str) -> None:
    conn.execute("DELETE FROM import_cursors WHERE filename = ?", (filename,))


def bulk_insert_executions(
    conn: sqlite3.Connection,
    executions: Sequence[Execution],
) -> tuple[int, int]:
    """Insert executions with ON CONFLICT DO NOTHING.

    Returns (inserted, skipped). Counts by comparing total_changes per row
    because SQLite's conflict resolution doesn't report per-row status.
    """
    if not executions:
        return (0, 0)
    inserted = 0
    for e in executions:
        before = conn.total_changes
        conn.execute(
            _INSERT_EXECUTION_SQL,
            (
                e.nt_execution_id, e.account, e.instrument, e.timestamp, e.side,
                e.original_action, e.quantity, e.price, e.commission, e.entry_exit,
                e.position_after, e.source_order_id, e.source_filename, e.imported_at,
            ),
        )
        if conn.total_changes > before:
            inserted += 1
    skipped = len(executions) - inserted
    return (inserted, skipped)


def insert_rejects(
    conn: sqlite3.Connection,
    tick_id: int,
    rejects: Iterable[RejectRecord],
) -> None:
    now = int(time.time())
    conn.executemany(
        "INSERT INTO import_rejects (tick_id, line_number, raw_line, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [(tick_id, r.line_number, r.raw_line, r.reason, now) for r in rejects],
    )


def record_run(
    conn: sqlite3.Connection,
    *,
    filename: str,
    started_at: int,
    finished_at: int,
    cursor_before: int,
    cursor_after: int,
    lines_read: int,
    rows_parsed: int,
    rows_inserted: int,
    rows_skipped_duplicate: int,
    rows_rejected: int,
    status: str,
    error: str | None,
) -> int:
    cur = conn.execute(
        "INSERT INTO import_runs ("
        " filename, started_at, finished_at, cursor_before, cursor_after,"
        " lines_read, rows_parsed, rows_inserted, rows_skipped_duplicate,"
        " rows_rejected, status, error"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            filename, started_at, finished_at, cursor_before, cursor_after,
            lines_read, rows_parsed, rows_inserted, rows_skipped_duplicate,
            rows_rejected, status, error,
        ),
    )
    return int(cur.lastrowid)


def delete_executions(
    conn: sqlite3.Connection,
    nt_execution_ids: Sequence[str],
) -> int:
    if not nt_execution_ids:
        return 0
    placeholders = ",".join("?" for _ in nt_execution_ids)
    cur = conn.execute(
        f"DELETE FROM executions WHERE nt_execution_id IN ({placeholders})",
        tuple(nt_execution_ids),
    )
    return int(cur.rowcount)
