from pathlib import Path

from db import connect
from services.notes import strip_split_suffix


def get_flag(db_path: Path | str, execution_id: str) -> dict:
    """Return {'reviewed': bool, 'reviewed_at': int|None}.

    Returns the default (unreviewed) shape when the row doesn't exist.
    """
    real_id = strip_split_suffix(execution_id)
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT reviewed, reviewed_at FROM execution_flags WHERE execution_id = ?",
            (real_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"reviewed": False, "reviewed_at": None}
    return {
        "reviewed": bool(row["reviewed"]),
        "reviewed_at": int(row["reviewed_at"]) if row["reviewed_at"] is not None else None,
    }


def set_reviewed(
    db_path: Path | str,
    *,
    execution_id: str,
    reviewed: bool,
    now: int,
) -> None:
    real_id = strip_split_suffix(execution_id)
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "INSERT INTO execution_flags (execution_id, reviewed, reviewed_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(execution_id) DO UPDATE SET "
                " reviewed = excluded.reviewed,"
                " reviewed_at = excluded.reviewed_at",
                (real_id, 1 if reviewed else 0, now),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def list_flags_for_executions(
    db_path: Path | str,
    execution_ids: list[str],
) -> dict[str, bool]:
    """Return a {real_execution_id: reviewed_bool} map. Unreviewed
    executions are omitted from the dict entirely (callers that want the
    default can default-from-missing)."""
    if not execution_ids:
        return {}
    real_ids = sorted({strip_split_suffix(i) for i in execution_ids})
    placeholders = ",".join("?" for _ in real_ids)
    conn = connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT execution_id, reviewed FROM execution_flags "
            f"WHERE execution_id IN ({placeholders}) AND reviewed = 1",
            tuple(real_ids),
        ).fetchall()
    finally:
        conn.close()
    return {r["execution_id"]: True for r in rows}
