from pathlib import Path

from db import connect
from migrations import applied_versions, run_migrations


def _migrate(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def test_005_applied(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        assert "005_browsing" in applied_versions(conn)
    finally:
        conn.close()


def test_execution_notes_shape(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(execution_notes)").fetchall()}
        assert cols == {"execution_id", "note", "updated_at"}
        fks = conn.execute("PRAGMA foreign_key_list(execution_notes)").fetchall()
        assert fks[0][2] == "executions"  # references
        assert fks[0][3] == "execution_id"  # from
        assert fks[0][4] == "nt_execution_id"  # to
        assert fks[0][6] == "CASCADE"
    finally:
        conn.close()


def test_execution_flags_shape(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(execution_flags)").fetchall()}
        assert cols == {"execution_id", "reviewed", "reviewed_at"}
        fks = conn.execute("PRAGMA foreign_key_list(execution_flags)").fetchall()
        assert fks[0][2] == "executions"
        assert fks[0][6] == "CASCADE"
    finally:
        conn.close()


def test_link_groups_shape(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(link_groups)").fetchall()}
        assert cols == {"link_group_id", "label", "created_at"}
    finally:
        conn.close()


def test_position_links_shape(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(position_links)").fetchall()}
        assert cols == {
            "link_group_id",
            "account",
            "instrument",
            "entry_execution_id",
            "ordinal",
        }
        pk_cols = sorted(
            r[1] for r in conn.execute("PRAGMA table_info(position_links)").fetchall() if r[5] > 0
        )
        assert pk_cols == [
            "account",
            "entry_execution_id",
            "instrument",
            "link_group_id",
        ]
        fks = conn.execute("PRAGMA foreign_key_list(position_links)").fetchall()
        assert any(fk[2] == "link_groups" and fk[6] == "CASCADE" for fk in fks)
    finally:
        conn.close()


def test_cascade_delete_execution_cleans_note_and_flag(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO executions "
            "(nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit,"
            " position_after, source_order_id, source_filename, imported_at) "
            "VALUES ('abc','A','MNQ',1,'Buy','Buy',1,100.0,0.0,'Entry','1 L',NULL,'f.csv',1)"
        )
        conn.execute(
            "INSERT INTO execution_notes (execution_id, note, updated_at) "
            "VALUES ('abc','hello',1)"
        )
        conn.execute(
            "INSERT INTO execution_flags (execution_id, reviewed, reviewed_at) "
            "VALUES ('abc',1,1)"
        )
        conn.execute("COMMIT")
        conn.execute("DELETE FROM executions WHERE nt_execution_id='abc'")
        assert conn.execute("SELECT COUNT(*) FROM execution_notes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM execution_flags").fetchone()[0] == 0
    finally:
        conn.close()
