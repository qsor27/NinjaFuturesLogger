from pathlib import Path

from db import read_conn, sql_placeholders, transaction


def strip_split_suffix(execution_id: str) -> str:
    """Remove a #close or #open suffix produced by the position-builder
    reversal splitter. Any other suffix passes through unchanged.

    User metadata (notes, flags, custom fields) is always keyed on the
    underlying real execution row; split halves share their parent's
    metadata.
    """
    for suffix in ("#close", "#open"):
        if execution_id.endswith(suffix):
            return execution_id[: -len(suffix)]
    return execution_id


def get_note(db_path: Path | str, execution_id: str) -> dict | None:
    """Return {'note', 'updated_at'} for the execution, or None."""
    real_id = strip_split_suffix(execution_id)
    with read_conn(db_path) as conn:
        row = conn.execute(
            "SELECT note, updated_at FROM execution_notes WHERE execution_id = ?",
            (real_id,),
        ).fetchone()
    if row is None:
        return None
    return {"note": row["note"], "updated_at": int(row["updated_at"])}


def upsert_note(
    db_path: Path | str,
    *,
    execution_id: str,
    note: str,
    now: int,
) -> None:
    """Insert or update a note on a real execution. Raises if the execution
    does not exist (FK violation bubbles up)."""
    real_id = strip_split_suffix(execution_id)
    with transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO execution_notes (execution_id, note, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(execution_id) DO UPDATE SET "
            " note = excluded.note,"
            " updated_at = excluded.updated_at",
            (real_id, note, now),
        )


def delete_note(db_path: Path | str, execution_id: str) -> None:
    real_id = strip_split_suffix(execution_id)
    with transaction(db_path) as conn:
        conn.execute(
            "DELETE FROM execution_notes WHERE execution_id = ?",
            (real_id,),
        )


def list_notes_for_executions(
    db_path: Path | str,
    execution_ids: list[str],
) -> dict[str, str]:
    """Return a {real_execution_id: note} map for a batch of IDs.

    Input IDs may contain split-fill suffixes; they are stripped before
    lookup. The returned dict uses real (un-suffixed) keys.
    """
    if not execution_ids:
        return {}
    real_ids = sorted({strip_split_suffix(i) for i in execution_ids})
    with read_conn(db_path) as conn:
        rows = conn.execute(
            f"SELECT execution_id, note FROM execution_notes "
            f"WHERE execution_id IN ({sql_placeholders(len(real_ids))})",
            tuple(real_ids),
        ).fetchall()
    return {r["execution_id"]: r["note"] for r in rows}
