from pathlib import Path

from db import connect
from migrations import run_migrations


def test_migration_011_creates_all_four_tables(tmp_path):
    db = tmp_path / "t.db"
    conn = connect(db)
    try:
        run_migrations(conn, Path("migrations"))
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    for expected in (
        "fetch_attempts",
        "fetch_source_attempts",
        "ohlc_gap_reports",
        "ohlc_breaker_state",
    ):
        assert expected in tables, f"missing table: {expected}"
