"""Persist CircuitBreaker state across restarts.

Called from fetcher after every record_success / record_failure, and from
build_default_registry on startup (via load_breaker) so a container that
restarts during a backoff respects the remaining cooldown.
"""

from __future__ import annotations

import sqlite3

from services.ohlc.circuit_breaker import CircuitBreaker


def persist_breaker(
    conn: sqlite3.Connection,
    breaker: CircuitBreaker,
    *,
    now: int,
) -> None:
    snap = breaker.snapshot()
    conn.execute(
        "INSERT INTO ohlc_breaker_state"
        " (source, state, consecutive_failures, consecutive_trips,"
        "  current_cooldown_seconds, opened_at, next_retry_at,"
        "  last_failure_at, last_success_at, last_error,"
        "  last_failure_class, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(source) DO UPDATE SET"
        "  state = excluded.state,"
        "  consecutive_failures = excluded.consecutive_failures,"
        "  consecutive_trips = excluded.consecutive_trips,"
        "  current_cooldown_seconds = excluded.current_cooldown_seconds,"
        "  opened_at = excluded.opened_at,"
        "  next_retry_at = excluded.next_retry_at,"
        "  last_failure_at = excluded.last_failure_at,"
        "  last_success_at = excluded.last_success_at,"
        "  last_error = excluded.last_error,"
        "  last_failure_class = excluded.last_failure_class,"
        "  updated_at = excluded.updated_at",
        (
            breaker.name,
            snap["state"],
            snap["consecutive_failures"],
            snap["consecutive_trips"],
            snap["current_cooldown_seconds"],
            snap["opened_at"],
            snap["next_retry_at"],
            snap["last_failure_at"],
            snap["last_success_at"],
            snap["last_error"],
            snap["last_failure_class"],
            now,
        ),
    )


def load_breaker(
    conn: sqlite3.Connection,
    breaker: CircuitBreaker,
) -> None:
    row = conn.execute(
        "SELECT * FROM ohlc_breaker_state WHERE source = ?",
        (breaker.name,),
    ).fetchone()
    if row is None:
        return
    breaker.restore({k: row[k] for k in row.keys()})
