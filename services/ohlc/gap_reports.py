"""Gap-report writer + retry scheduling helpers.

A *gap report* is a persistent record that a specific (instrument, timeframe,
range) is missing bars the provider should have served. One row per distinct
gap, UPSERTed; the self-heal scheduler retries them with exponential backoff.

Rules:
- Gaps younger than 1 hour are ignored (provider may simply not have closed
  the bar yet).
- Gaps that fall outside provider reach are not recorded (cannot be filled).
- The only function that *writes* gap-report rows is update_gap_reports.
  Callers never INSERT directly. This is the single place the 1h grace rule
  and the reach filter are applied.
"""

from __future__ import annotations

import sqlite3

from services.ohlc.gap_detection import find_gaps
from services.ohlc.reach import PROVIDER_REACH

GRACE_SECONDS = 3600  # "ignore gaps younger than 1 hour"
BACKOFF_BASE_SECONDS = 3600
BACKOFF_MAX_SECONDS = 24 * 3600
ABANDON_AFTER_ATTEMPTS = 10


def compute_backoff(attempt_count: int) -> int:
    """Return seconds until the next retry after `attempt_count` failures."""
    if attempt_count < 1:
        return 0
    value = BACKOFF_BASE_SECONDS * (2 ** (attempt_count - 1))
    return min(value, BACKOFF_MAX_SECONDS)


def update_gap_reports(
    conn: sqlite3.Connection,
    *,
    instrument: str,
    timeframe: str,
    range_start: int,
    range_end: int,
    attempt_id: str | None,
    now: int,
) -> None:
    """Recompute gaps in [range_start, range_end); upsert open rows + resolve filled ones.

    Called as the final step inside fetch_range (and by self_heal when re-checking).
    - Any gap older than 1h and inside provider reach → upsert an open row.
    - Any existing open row whose gap is now covered → mark resolved.
    - Any existing open row whose gap is now out of reach → mark abandoned.
    """
    current_gaps = find_gaps(
        conn,
        instrument=instrument,
        timeframe=timeframe,
        start=range_start,
        end=range_end,
    )
    reach = PROVIDER_REACH.get(timeframe)
    reach_floor = (now - reach) if reach is not None else None

    still_missing: set[tuple[int, int]] = set()
    for g_start, g_end in current_gaps:
        # 1h grace: skip gaps where the last slot is younger than 1h.
        if now - g_end < GRACE_SECONDS:
            continue
        # Reach filter: skip gaps entirely before provider reach floor.
        if reach_floor is not None and g_end <= reach_floor:
            continue
        still_missing.add((g_start, g_end))
        conn.execute(
            "INSERT INTO ohlc_gap_reports"
            " (instrument, timeframe, gap_start, gap_end, first_seen_at,"
            "  attempt_count, next_retry_at, state)"
            " VALUES (?, ?, ?, ?, ?, 0, ?, 'open')"
            " ON CONFLICT(instrument, timeframe, gap_start, gap_end)"
            "  DO NOTHING",
            (instrument, timeframe, g_start, g_end, now, now),
        )

    # Resolve any open rows in this window whose gap is no longer reported
    # by find_gaps — i.e. the bars were written successfully.
    opens = conn.execute(
        "SELECT id, gap_start, gap_end FROM ohlc_gap_reports"
        " WHERE instrument = ? AND timeframe = ? AND state = 'open'"
        "   AND gap_start >= ? AND gap_end <= ?",
        (instrument, timeframe, range_start, range_end),
    ).fetchall()
    for row in opens:
        if (row["gap_start"], row["gap_end"]) in still_missing:
            continue
        conn.execute(
            "UPDATE ohlc_gap_reports"
            " SET state = 'resolved', resolved_at = ?, last_attempt_id = ?"
            " WHERE id = ?",
            (now, attempt_id, row["id"]),
        )


def list_open(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM ohlc_gap_reports WHERE state = 'open'"
        " ORDER BY next_retry_at ASC"
    ).fetchall()


def select_due(
    conn: sqlite3.Connection, *, now: int, limit: int,
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM ohlc_gap_reports"
        " WHERE state = 'open' AND next_retry_at <= ?"
        " ORDER BY next_retry_at ASC LIMIT ?",
        (now, limit),
    ).fetchall()


def record_retry_outcome(
    conn: sqlite3.Connection,
    *,
    gap_id: int,
    attempt_id: str,
    resolved: bool,
    now: int,
) -> None:
    """Update a gap-report row after a self-heal fetch attempt."""
    if resolved:
        conn.execute(
            "UPDATE ohlc_gap_reports"
            " SET state='resolved', resolved_at=?, last_attempt_id=?,"
            "     last_attempt_at=?"
            " WHERE id=?",
            (now, attempt_id, now, gap_id),
        )
        return

    row = conn.execute(
        "SELECT attempt_count FROM ohlc_gap_reports WHERE id=?", (gap_id,),
    ).fetchone()
    new_count = int(row["attempt_count"]) + 1
    if new_count >= ABANDON_AFTER_ATTEMPTS:
        conn.execute(
            "UPDATE ohlc_gap_reports"
            " SET state='abandoned', attempt_count=?, last_attempt_id=?,"
            "     last_attempt_at=?"
            " WHERE id=?",
            (new_count, attempt_id, now, gap_id),
        )
        return
    conn.execute(
        "UPDATE ohlc_gap_reports"
        " SET attempt_count=?, last_attempt_id=?, last_attempt_at=?,"
        "     next_retry_at=?"
        " WHERE id=?",
        (new_count, attempt_id, now, now + compute_backoff(new_count), gap_id),
    )


def reset_for_retry(
    conn: sqlite3.Connection, *, gap_id: int, now: int,
) -> None:
    """User clicked 'Retry now' — reopen, clear counters, schedule immediate retry."""
    conn.execute(
        "UPDATE ohlc_gap_reports"
        " SET state='open', attempt_count=0, next_retry_at=?, resolved_at=NULL"
        " WHERE id=?",
        (now, gap_id),
    )
