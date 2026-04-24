"""Support bundle assembly.

Zips together the forensic trail a remote user needs for troubleshooting:
recent observability rows from SQLite, JSON log files, app config,
instrument registry, and a version stamp. Read-only — no side effects.
"""

import io
import json
import zipfile
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


_LOG_FILE_GLOB = "app.jsonl*"


def build_bundle(
    *,
    db_path: Path | str,
    log_dir: Path | str,
    config_dir: Path | str,
    version: dict[str, str],
    days: int,
    now: int,
    system_health: dict | None = None,
) -> bytes:
    """Assemble the full support bundle as a zip in memory.

    Zip layout:
        version.json            — version stamp (git sha, built-at, image tag)
        snapshot.json           — snapshot_db output, pretty-printed
        system_health.json      — BackgroundServices snapshot (if provided)
        config/app.json         — verbatim (if present)
        config/instruments.json — verbatim (if present)
        logs/app.jsonl          — current log file (if present)
        logs/app.jsonl.1 …      — rotated log files, most recent first

    All path arguments may point at directories that do not exist; those
    sections are simply omitted from the zip.
    """
    snap = snapshot_db(db_path, days=days, now=now)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("version.json", json.dumps(version, indent=2))
        zf.writestr("snapshot.json", json.dumps(snap, indent=2, default=str))

        if system_health is not None:
            zf.writestr(
                "system_health.json",
                json.dumps(system_health, indent=2, default=str),
            )

        config_dir_path = Path(config_dir)
        for name in ("app.json", "instruments.json"):
            p = config_dir_path / name
            if p.is_file():
                zf.write(str(p), arcname=f"config/{name}")

        log_dir_path = Path(log_dir)
        if log_dir_path.is_dir():
            for p in sorted(log_dir_path.glob(_LOG_FILE_GLOB)):
                if p.is_file():
                    zf.write(str(p), arcname=f"logs/{p.name}")

    return buf.getvalue()
