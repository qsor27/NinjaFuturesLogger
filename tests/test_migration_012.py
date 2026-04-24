from pathlib import Path

from db import connect
from migrations import run_migrations


def test_user_preferences_table_exists_after_migration(tmp_path):
    db = tmp_path / "app.db"
    conn = connect(db)
    try:
        run_migrations(conn, Path("migrations"))
        row = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='user_preferences'"
        ).fetchone()
        assert row is not None
        cols = {c["name"]: c for c in conn.execute("PRAGMA table_info(user_preferences)")}
        assert cols.keys() == {"key", "value", "updated_at"}
        assert cols["key"]["pk"] == 1
        assert cols["key"]["notnull"] == 1
        assert cols["updated_at"]["notnull"] == 1
    finally:
        conn.close()
