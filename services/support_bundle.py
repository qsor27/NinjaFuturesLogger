"""Support bundle assembly.

Zips together the forensic trail a remote user needs for troubleshooting:
recent observability rows from SQLite, JSON log files, app config,
instrument registry, and a version stamp. Read-only — no side effects.
"""

from pathlib import Path

from db import connect

MAX_ROWS_PER_TABLE = 10_000

# (table_name, ts_column_for_windowing_or_None, order_by_expr)
# None means "take all rows up to MAX_ROWS_PER_TABLE, ordered by primary key desc".
_SNAPSHOT_TABLES: tuple[tuple[str, str | None, str], ...] = (
    ("fetch_attempts", "started_at", "started_at DESC"),
    ("fetch_source_attempts", None, "id DESC"),
    ("ohlc_gap_reports", "first_seen_at", "first_seen_at DESC"),
    ("ohlc_breaker_state", None, "source ASC"),
    ("import_runs", "started_at", "started_at DESC"),
    ("import_rejects", "created_at", "created_at DESC"),
    ("integrity_issues", "detected_at", "detected_at DESC"),
    ("schema_migrations", None, "applied_at DESC"),
)


def snapshot_db(
    db_path: Path | str,
    *,
    days: int,
    now: int,
) -> dict[str, list[dict]]:
    """Snapshot the observability tables to plain Python dicts.

    Windows time-series tables to the last `days` days (by the table's
    timestamp column). Caps each table at MAX_ROWS_PER_TABLE, newest first.
    Returns a dict keyed by table name with a list of JSON-friendly rows.
    """
    cutoff = now - days * 86400
    out: dict[str, list[dict]] = {}
    conn = connect(db_path)
    try:
        for table, ts_col, order_by in _SNAPSHOT_TABLES:
            if ts_col is not None:
                sql = f"SELECT * FROM {table} WHERE {ts_col} >= ? ORDER BY {order_by} LIMIT ?"
                rows = conn.execute(sql, (cutoff, MAX_ROWS_PER_TABLE)).fetchall()
            else:
                sql = f"SELECT * FROM {table} ORDER BY {order_by} LIMIT ?"
                rows = conn.execute(sql, (MAX_ROWS_PER_TABLE,)).fetchall()
            out[table] = [dict(r) for r in rows]
    finally:
        conn.close()
    return out
