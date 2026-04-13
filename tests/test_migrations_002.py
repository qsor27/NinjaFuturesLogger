from pathlib import Path

from db import connect
from migrations import applied_versions, run_migrations


def _migrate(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def test_002_is_applied(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        assert "002_executions" in applied_versions(conn)
    finally:
        conn.close()


def test_executions_table_columns(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(executions)").fetchall()}
        assert cols == {
            "nt_execution_id", "account", "instrument", "timestamp",
            "side", "original_action", "quantity", "price", "commission",
            "entry_exit", "position_after", "source_order_id",
            "source_filename", "imported_at",
        }
    finally:
        conn.close()


def test_executions_primary_key_is_composite(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        rows = conn.execute("PRAGMA table_info(executions)").fetchall()
        pk_cols = sorted([r[1] for r in rows if r[5] > 0], key=lambda c: c)
        assert pk_cols == ["account", "nt_execution_id"]
    finally:
        conn.close()


def test_executions_on_conflict_do_nothing(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        insert = (
            "INSERT INTO executions "
            "(nt_execution_id, account, instrument, timestamp, side, "
            " original_action, quantity, price, commission, entry_exit, "
            " position_after, source_order_id, source_filename, imported_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT DO NOTHING"
        )
        row = ("abc", "Sim101", "MNQ", 1700000000, "Buy", "Buy", 1, 4237.75,
               0.0, "Entry", "1 L", "order1", "file.csv", 1700000001)
        conn.execute(insert, row)
        conn.execute(insert, row)
        count = conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_executions_unique_index_on_nt_execution_id(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        indexes = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='index' AND tbl_name='executions'"
        ).fetchall()
        names = {r[0] for r in indexes}
        assert "idx_executions_nt_execution_id" in names
        row = next(r for r in indexes if r[0] == "idx_executions_nt_execution_id")
        assert "UNIQUE" in (row[1] or "").upper()
    finally:
        conn.close()


def test_import_cursors_table(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(import_cursors)").fetchall()}
        assert cols == {"filename", "byte_offset", "last_tick_at", "last_modified"}
    finally:
        conn.close()


def test_import_runs_table(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(import_runs)").fetchall()}
        assert {"tick_id", "filename", "started_at", "finished_at",
                "cursor_before", "cursor_after", "lines_read", "rows_parsed",
                "rows_inserted", "rows_skipped_duplicate", "rows_rejected",
                "status", "error"}.issubset(cols)
    finally:
        conn.close()


def test_import_rejects_table(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(import_rejects)").fetchall()}
        assert cols == {"reject_id", "tick_id", "line_number", "raw_line",
                        "reason", "created_at"}
    finally:
        conn.close()
