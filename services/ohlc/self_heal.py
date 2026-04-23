"""Self-heal scheduler tick.

Reads due ohlc_gap_reports rows, calls fetch_fn per row, then walks the
bars table to see if the gap is now covered. Updates each row via
record_retry_outcome — resolving, backing off, or abandoning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from db import connect
from logging_config import get_logger
from services.ohlc.gap_detection import find_gaps
from services.ohlc.gap_reports import (
    record_retry_outcome,
    select_due,
)

log = get_logger("ohlc.self_heal")


class FetchFn(Protocol):
    def __call__(
        self,
        *,
        db_path: Path | str,
        instrument: str,
        timeframe: str,
        start: int,
        end: int,
        trigger: str,
    ) -> None: ...


def self_heal_tick(
    *,
    db_path: Path | str,
    fetch_fn: FetchFn,
    now: int,
    limit: int = 20,
) -> None:
    conn = connect(db_path)
    try:
        rows = select_due(conn, now=now, limit=limit)
    finally:
        conn.close()

    for row in rows:
        gap_id = row["id"]
        instrument = row["instrument"]
        timeframe = row["timeframe"]
        gap_start = row["gap_start"]
        gap_end = row["gap_end"]
        try:
            fetch_fn(
                db_path=db_path,
                instrument=instrument,
                timeframe=timeframe,
                start=gap_start,
                end=gap_end,
                trigger="self_heal",
            )
        except Exception:
            log.exception(
                "self-heal fetch raised",
                extra={
                    "instrument": instrument,
                    "tf": timeframe,
                    "gap_start": gap_start,
                    "gap_end": gap_end,
                },
            )
            # Treat as a failed attempt — back off.
            conn = connect(db_path)
            try:
                conn.execute("BEGIN")
                record_retry_outcome(
                    conn,
                    gap_id=gap_id,
                    attempt_id=None,
                    resolved=False,
                    now=now,
                )
                conn.execute("COMMIT")
            finally:
                conn.close()
            continue

        # Did the fetch actually close the gap?
        conn = connect(db_path)
        try:
            remaining = find_gaps(
                conn,
                instrument=instrument,
                timeframe=timeframe,
                start=gap_start,
                end=gap_end,
            )
            still_open = any(
                g[0] == gap_start and g[1] == gap_end for g in remaining
            )
            conn.execute("BEGIN")
            record_retry_outcome(
                conn,
                gap_id=gap_id,
                attempt_id=None,
                resolved=not still_open,
                now=now,
            )
            conn.execute("COMMIT")
        finally:
            conn.close()
