from pathlib import Path

from db import connect
from migrations import applied_versions, run_migrations


def _migrate(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def test_003_is_applied(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        assert "003_integrity_issues" in applied_versions(conn)
    finally:
        conn.close()


def test_integrity_issues_columns(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(integrity_issues)").fetchall()}
        assert cols == {
            "issue_id",
            "account",
            "instrument",
            "execution_id",
            "severity",
            "type",
            "description",
            "detected_at",
            "last_seen_at",
            "resolved_at",
            "resolved_by",
            "resolution_note",
            "ignored",
            "ignore_note",
        }
    finally:
        conn.close()


def test_integrity_issues_unique_key(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        insert = (
            "INSERT INTO integrity_issues "
            "(account, instrument, execution_id, severity, type, description,"
            " detected_at, last_seen_at, ignored) "
            "VALUES (?,?,?,?,?,?,?,?,0)"
        )
        row = ("Sim101", "MNQ", "abc", "high", "position_column_mismatch", "x", 1, 1)
        conn.execute(insert, row)
        try:
            conn.execute(insert, row)
            raised = False
        except Exception:
            raised = True
        assert raised
    finally:
        conn.close()


def test_integrity_open_partial_index_exists(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='index' AND tbl_name='integrity_issues'"
        ).fetchall()
        names = {r[0] for r in rows}
        assert "idx_integrity_open" in names
    finally:
        conn.close()
