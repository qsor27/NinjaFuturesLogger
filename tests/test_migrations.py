from pathlib import Path

from db import connect
from migrations import applied_versions, run_migrations


def test_baseline_migration_is_applied(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    versions = applied_versions(conn)
    assert "001_baseline" in versions
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {r[0] for r in rows}
    assert "schema_migrations" in table_names


def test_run_migrations_is_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    run_migrations(conn, Path("migrations"))  # second run: no-op
    count = conn.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version='001_baseline'"
    ).fetchone()[0]
    assert count == 1
