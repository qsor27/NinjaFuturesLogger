"""Persistence for review sessions and attempts. Summary math lives here too:
it is one GROUP BY away from the rows, and keeping it next to the writes keeps
the 2x2 definition (won = net > 0, lost = net < 0, scratch = 0) in one place."""

from pathlib import Path

from db import connect
from models.review import ReviewCall, ReviewSummary, SummaryCell
from services.notes import strip_split_suffix


def create_session(db_path: Path | str, *, now: int) -> int:
    conn = connect(db_path)
    try:
        cur = conn.execute("INSERT INTO review_sessions (started_at) VALUES (?)", (now,))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def session_exists(db_path: Path | str, session_id: int) -> bool:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM review_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def end_session(db_path: Path | str, session_id: int, *, now: int) -> bool:
    conn = connect(db_path)
    try:
        if not conn.execute(
            "SELECT 1 FROM review_sessions WHERE session_id = ?", (session_id,)
        ).fetchone():
            return False
        conn.execute(
            "UPDATE review_sessions SET ended_at = COALESCE(ended_at, ?)" " WHERE session_id = ?",
            (now, session_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def record_attempt(
    db_path: Path | str,
    *,
    session_id: int,
    account: str,
    instrument: str,
    entry_execution_id: str,
    call: ReviewCall,
    outcome_pnl: float,
    now: int,
) -> int:
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO review_attempts (session_id, account, instrument,"
            " entry_execution_id, real_execution_id, call, outcome_pnl, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                account,
                instrument,
                entry_execution_id,
                strip_split_suffix(entry_execution_id),
                call,
                outcome_pnl,
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def has_attempt(db_path: Path | str, session_id: int, entry_execution_id: str) -> bool:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM review_attempts"
            " WHERE session_id = ? AND entry_execution_id = ? LIMIT 1",
            (session_id, entry_execution_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def attempt_stats(db_path: Path | str) -> dict[str, tuple[int, int]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT entry_execution_id, COUNT(*), MAX(created_at)"
            " FROM review_attempts GROUP BY entry_execution_id"
        ).fetchall()
        return {r[0]: (int(r[1]), int(r[2])) for r in rows}
    finally:
        conn.close()


def summary(db_path: Path | str, session_id: int | None = None) -> ReviewSummary:
    where = "WHERE session_id = ?" if session_id is not None else ""
    params = (session_id,) if session_id is not None else ()
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT call,"
            " CASE WHEN outcome_pnl > 0 THEN 'won'"
            "      WHEN outcome_pnl < 0 THEN 'lost'"
            "      ELSE 'scratch' END AS bucket,"
            " COUNT(*), COALESCE(SUM(outcome_pnl), 0)"
            f" FROM review_attempts {where} GROUP BY call, bucket",
            params,
        ).fetchall()
    finally:
        conn.close()

    cells = {
        f"{call}_{bucket}": SummaryCell(count=int(n), net_pnl=float(total))
        for call, bucket, n, total in rows
    }
    empty = SummaryCell(count=0, net_pnl=0.0)
    return ReviewSummary(
        valid_won=cells.get("valid_won", empty),
        valid_lost=cells.get("valid_lost", empty),
        valid_scratch=cells.get("valid_scratch", empty),
        invalid_won=cells.get("invalid_won", empty),
        invalid_lost=cells.get("invalid_lost", empty),
        invalid_scratch=cells.get("invalid_scratch", empty),
        attempts=sum(int(r[2]) for r in rows),
    )
