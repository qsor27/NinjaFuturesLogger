"""Per-contract coverage state machine.

Tracks (active | winding_down | retired) per instrument, derived from
executions plus user overrides (pinned, retired_at). Called once per
coverage-maintainer tick and on any user action.
"""

import sqlite3
from dataclasses import dataclass
from typing import Literal

State = Literal["active", "winding_down", "retired"]

ACTIVE_DAYS = 30
SAFETY_BACKSTOP_DAYS = 180


@dataclass(frozen=True)
class CoverageRow:
    instrument: str
    state: State
    last_execution_at: int | None
    pinned: bool
    retired_at: int | None
    updated_at: int


def list_coverage(conn: sqlite3.Connection) -> list[CoverageRow]:
    rows = conn.execute(
        "SELECT instrument, state, last_execution_at, pinned, retired_at, updated_at"
        " FROM instrument_coverage ORDER BY instrument"
    ).fetchall()
    return [
        CoverageRow(
            instrument=r["instrument"],
            state=r["state"],
            last_execution_at=r["last_execution_at"],
            pinned=bool(r["pinned"]),
            retired_at=r["retired_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def set_pinned(
    conn: sqlite3.Connection, *, instrument: str, pinned: bool, now: int
) -> None:
    conn.execute(
        "INSERT INTO instrument_coverage"
        " (instrument, state, last_execution_at, pinned, retired_at, updated_at)"
        " VALUES (?, 'active', NULL, ?, NULL, ?)"
        " ON CONFLICT(instrument) DO UPDATE SET"
        "  pinned = excluded.pinned,"
        "  updated_at = excluded.updated_at",
        (instrument, 1 if pinned else 0, now),
    )


def retire_now(conn: sqlite3.Connection, *, instrument: str, now: int) -> None:
    conn.execute(
        "INSERT INTO instrument_coverage"
        " (instrument, state, last_execution_at, pinned, retired_at, updated_at)"
        " VALUES (?, 'retired', NULL, 0, ?, ?)"
        " ON CONFLICT(instrument) DO UPDATE SET"
        "  state = 'retired',"
        "  pinned = 0,"
        "  retired_at = excluded.retired_at,"
        "  updated_at = excluded.updated_at",
        (instrument, now, now),
    )


def reactivate(conn: sqlite3.Connection, *, instrument: str, now: int) -> None:
    conn.execute(
        "UPDATE instrument_coverage"
        " SET state = 'active', retired_at = NULL, updated_at = ?"
        " WHERE instrument = ?",
        (now, instrument),
    )


def refresh_instrument_coverage_state(conn: sqlite3.Connection, *, now: int) -> None:
    """Recompute state for every instrument seen in executions and upsert.

    Respects pinned and retired_at overrides. Never transitions an
    explicitly-retired contract back to active — only reactivate() does.
    """
    rows = conn.execute(
        "SELECT instrument, MAX(timestamp) AS last_ts"
        " FROM executions GROUP BY instrument"
    ).fetchall()
    existing = {r.instrument: r for r in list_coverage(conn)}

    for row in rows:
        instrument = row["instrument"]
        last_ts = int(row["last_ts"])
        prev = existing.get(instrument)
        pinned = prev.pinned if prev is not None else False
        if prev is not None and prev.retired_at is not None and prev.state == "retired":
            continue
        state = _compute_state(last_ts=last_ts, pinned=pinned, now=now)
        conn.execute(
            "INSERT INTO instrument_coverage"
            " (instrument, state, last_execution_at, pinned, retired_at, updated_at)"
            " VALUES (?, ?, ?, ?, NULL, ?)"
            " ON CONFLICT(instrument) DO UPDATE SET"
            "  state = excluded.state,"
            "  last_execution_at = excluded.last_execution_at,"
            "  updated_at = excluded.updated_at",
            (instrument, state, last_ts, 1 if pinned else 0, now),
        )


def _compute_state(*, last_ts: int, pinned: bool, now: int) -> State:
    if pinned:
        return "active"
    age = now - last_ts
    if age <= ACTIVE_DAYS * 86400:
        return "active"
    if age >= SAFETY_BACKSTOP_DAYS * 86400:
        return "retired"
    return "winding_down"
