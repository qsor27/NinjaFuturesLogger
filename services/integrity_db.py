import sqlite3

from models.position import IntegrityIssue


def upsert_issue(conn: sqlite3.Connection, issue: IntegrityIssue, *, now: int) -> None:
    """Insert the issue if new; bump last_seen_at if it already exists.

    Keyed by UNIQUE(account, instrument, execution_id, type). Does not touch
    resolved_at or ignored so a stored resolution survives a re-detection.
    """
    conn.execute(
        "INSERT INTO integrity_issues "
        "(account, instrument, execution_id, severity, type, description,"
        " detected_at, last_seen_at, ignored) "
        "VALUES (?,?,?,?,?,?,?,?,0) "
        "ON CONFLICT(account, instrument, execution_id, type) DO UPDATE SET "
        " last_seen_at = excluded.last_seen_at,"
        " severity = excluded.severity,"
        " description = excluded.description",
        (
            issue.account,
            issue.instrument,
            issue.execution_id,
            issue.severity,
            issue.type,
            issue.description,
            now,
            now,
        ),
    )


def auto_resolve_missing(
    conn: sqlite3.Connection,
    *,
    account: str,
    instrument: str,
    present_keys: set[tuple[str, str]],
    now: int,
) -> None:
    """Mark as system-resolved every open issue for the pair not in `present_keys`.

    `present_keys` is a set of `(execution_id, type)` tuples currently produced
    by build_positions. Ignored issues are left alone.
    """
    rows = conn.execute(
        "SELECT issue_id, execution_id, type FROM integrity_issues "
        "WHERE account = ? AND instrument = ? AND resolved_at IS NULL AND ignored = 0",
        (account, instrument),
    ).fetchall()
    stale_ids = [
        r["issue_id"] for r in rows if (r["execution_id"], r["type"]) not in present_keys
    ]
    if not stale_ids:
        return
    placeholders = ",".join("?" for _ in stale_ids)
    conn.execute(
        f"UPDATE integrity_issues SET resolved_at = ?, resolved_by = 'system' "
        f"WHERE issue_id IN ({placeholders})",
        (now, *stale_ids),
    )


def list_open_for_pair(
    conn: sqlite3.Connection,
    account: str,
    instrument: str,
) -> list:
    return conn.execute(
        "SELECT * FROM integrity_issues "
        "WHERE account = ? AND instrument = ? "
        "  AND resolved_at IS NULL AND ignored = 0 "
        "ORDER BY issue_id",
        (account, instrument),
    ).fetchall()


def mark_resolved_by_user(
    conn: sqlite3.Connection,
    *,
    issue_id: int,
    now: int,
    note: str | None,
) -> None:
    conn.execute(
        "UPDATE integrity_issues SET resolved_at = ?, resolved_by = 'user', "
        " resolution_note = ? WHERE issue_id = ?",
        (now, note, issue_id),
    )


def mark_ignored(conn: sqlite3.Connection, *, issue_id: int, note: str) -> None:
    conn.execute(
        "UPDATE integrity_issues SET ignored = 1, ignore_note = ? WHERE issue_id = ?",
        (note, issue_id),
    )
