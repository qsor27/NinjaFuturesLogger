import sqlite3
import time
from pathlib import Path


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)"
    )


def applied_versions(conn: sqlite3.Connection) -> set[str]:
    _ensure_table(conn)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def run_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> list[str]:
    """Apply any *.sql files in `migrations_dir` not yet recorded.

    Files are applied in lexicographic filename order. Each file runs in
    one transaction; on failure the transaction rolls back and the version
    is not recorded, so the same file will be retried on next startup.
    """
    _ensure_table(conn)
    already = applied_versions(conn)
    files = sorted(migrations_dir.glob("*.sql"))
    newly_applied: list[str] = []
    for f in files:
        version = f.stem
        if version in already:
            continue
        sql = f.read_text(encoding="utf-8")
        # `executescript` unconditionally issues COMMIT before running, so we
        # cannot wrap it with an outer BEGIN/COMMIT. Instead we embed the
        # transaction markers plus the version-record INSERT into the script
        # itself, making the whole migration atomic in one call.
        applied_at = int(time.time())
        version_sql = version.replace("'", "''")
        script = (
            "BEGIN;\n"
            f"{sql}\n"
            f"INSERT INTO schema_migrations (version, applied_at) "
            f"VALUES ('{version_sql}', {applied_at});\n"
            "COMMIT;\n"
        )
        try:
            conn.executescript(script)
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
        newly_applied.append(version)
    return newly_applied
