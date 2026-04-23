"""Writer API for the fetch_attempts / fetch_source_attempts tables.

Called only from services/ohlc/fetcher.py (begin / record / complete) and
from app startup + a nightly retention job (orphan_sweep / trim_older_than).
No route calls these directly; the dashboard reads the tables through
routes/ohlc.py.
"""

from __future__ import annotations

import sqlite3
import uuid


def new_attempt_id() -> str:
    return uuid.uuid4().hex


def begin_attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    trigger: str,
    instrument: str,
    timeframe: str,
    range_start: int,
    range_end: int,
    now: int,
) -> None:
    conn.execute(
        "INSERT INTO fetch_attempts"
        " (id, trigger, instrument, timeframe, range_start, range_end, started_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (attempt_id, trigger, instrument, timeframe, range_start, range_end, now),
    )


def record_source_attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    gap_start: int,
    gap_end: int,
    source: str,
    outcome: str,
    bars_returned: int,
    duration_ms: int | None,
    http_status: int | None,
    error_class: str | None,
    error: str | None,
) -> None:
    conn.execute(
        "INSERT INTO fetch_source_attempts"
        " (attempt_id, gap_start, gap_end, source, outcome,"
        "  bars_returned, duration_ms, http_status, error_class, error)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            attempt_id,
            gap_start,
            gap_end,
            source,
            outcome,
            bars_returned,
            duration_ms,
            http_status,
            error_class,
            error,
        ),
    )


def complete_attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    now: int,
    gaps_found: int,
    bars_written: int,
    final_status: str,
    error: str | None,
) -> None:
    conn.execute(
        "UPDATE fetch_attempts SET"
        "  completed_at = ?,"
        "  gaps_found = ?,"
        "  bars_written = ?,"
        "  final_status = ?,"
        "  error = ?"
        " WHERE id = ?",
        (now, gaps_found, bars_written, final_status, error, attempt_id),
    )


def orphan_sweep(conn: sqlite3.Connection, *, now: int) -> int:
    """Close any attempt rows that were started but never completed.

    Called once on app startup. Returns the count of rows closed.
    """
    cur = conn.execute(
        "UPDATE fetch_attempts SET"
        "  completed_at = ?,"
        "  final_status = 'interrupted',"
        "  error = 'process restarted while running'"
        " WHERE completed_at IS NULL",
        (now,),
    )
    return cur.rowcount


def trim_older_than(conn: sqlite3.Connection, *, cutoff: int) -> int:
    """Delete attempt rows with started_at < cutoff.

    fetch_source_attempts cascades via FK ON DELETE CASCADE.
    """
    cur = conn.execute(
        "DELETE FROM fetch_attempts WHERE started_at < ?",
        (cutoff,),
    )
    return cur.rowcount
