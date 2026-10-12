import shutil
from pathlib import Path

from db import connect
from migrations import run_migrations


def test_executions_has_nullable_order_name(tmp_path):
    conn = connect(tmp_path / "app.db")
    try:
        run_migrations(conn, Path("migrations"))
        cols = {c["name"]: c for c in conn.execute("PRAGMA table_info(executions)")}
        assert "order_name" in cols
        assert cols["order_name"]["notnull"] == 0
    finally:
        conn.close()


def test_migration_015_preserves_existing_rows(tmp_path):
    # Apply everything before 015, insert a row, then apply 015.
    pre = tmp_path / "pre"
    pre.mkdir()
    for f in sorted(Path("migrations").glob("*.sql")):
        if f.stem < "015":
            shutil.copy(f, pre / f.name)
    conn = connect(tmp_path / "app.db")
    try:
        run_migrations(conn, pre)
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit, position_after,"
            " source_order_id, source_filename, imported_at)"
            " VALUES ('x1','Sim','MNQ',1,'Buy','Buy',1,100.0,0,'Entry','1 L',NULL,'f.csv',1)"
        )
        conn.commit()
        run_migrations(conn, Path("migrations"))
        row = conn.execute("SELECT nt_execution_id, order_name FROM executions").fetchone()
        assert row["nt_execution_id"] == "x1"
        assert row["order_name"] is None
    finally:
        conn.close()
