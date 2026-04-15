import sqlite3
import tempfile
from pathlib import Path

from db import connect
from migrations import run_migrations


def _fresh_db() -> sqlite3.Connection:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = connect(Path(tmp.name))
    run_migrations(conn, Path("migrations"))
    return conn


def test_chart_defaults_table_exists_with_seed_row():
    conn = _fresh_db()
    try:
        rows = conn.execute(
            "SELECT id, default_timeframe, volume_visible_default FROM chart_defaults"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["id"] == 1
        assert rows[0]["default_timeframe"] == "5m"
        assert rows[0]["volume_visible_default"] == 1
    finally:
        conn.close()


def test_chart_defaults_single_row_check_rejects_second_insert():
    conn = _fresh_db()
    try:
        try:
            conn.execute("INSERT INTO chart_defaults (id, updated_at) VALUES (2, 0)")
            raise AssertionError("expected CHECK(id=1) to reject id=2")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_custom_fields_tables_exist_with_expected_columns():
    conn = _fresh_db()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(custom_fields)").fetchall()}
        assert cols == {
            "field_id",
            "name",
            "field_type",
            "is_active",
            "display_order",
            "created_at",
        }

        cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(custom_field_options)").fetchall()
        }
        assert cols == {"option_id", "field_id", "value", "display_order"}

        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(execution_custom_field_values)").fetchall()
        }
        assert cols == {"execution_id", "field_id", "value", "updated_at"}
    finally:
        conn.close()


def test_custom_fields_field_type_check_rejects_bad_type():
    conn = _fresh_db()
    try:
        try:
            conn.execute(
                "INSERT INTO custom_fields (name, field_type, created_at) VALUES ('x', 'bogus', 0)"
            )
            raise AssertionError("expected CHECK(field_type IN ...) to reject 'bogus'")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_custom_field_options_unique_per_field():
    conn = _fresh_db()
    try:
        conn.execute(
            "INSERT INTO custom_fields (name, field_type, created_at) VALUES ('setup', 'dropdown', 0)"
        )
        fid = conn.execute("SELECT field_id FROM custom_fields WHERE name='setup'").fetchone()[0]
        conn.execute(
            "INSERT INTO custom_field_options (field_id, value, display_order) VALUES (?, 'Breakout', 0)",
            (fid,),
        )
        try:
            conn.execute(
                "INSERT INTO custom_field_options (field_id, value, display_order) VALUES (?, 'Breakout', 1)",
                (fid,),
            )
            raise AssertionError("expected UNIQUE(field_id, value) to reject")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_execution_custom_field_values_cascade_on_execution_delete():
    conn = _fresh_db()
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit, position_after,"
            " source_order_id, source_filename, imported_at) VALUES "
            "('E1', 'Sim', 'MES', 1700000000, 'Buy', 'Buy', 1, 4500.0, 2.50, 'Entry', 1, 'O', 'f.csv', 1700000000)"
        )
        conn.execute(
            "INSERT INTO custom_fields (name, field_type, created_at) VALUES ('setup', 'text', 0)"
        )
        fid = conn.execute("SELECT field_id FROM custom_fields WHERE name='setup'").fetchone()[0]
        conn.execute(
            "INSERT INTO execution_custom_field_values (execution_id, field_id, value, updated_at) "
            "VALUES ('E1', ?, 'A+', 0)",
            (fid,),
        )
        conn.execute("COMMIT")

        conn.execute("BEGIN")
        conn.execute("DELETE FROM executions WHERE nt_execution_id = 'E1'")
        conn.execute("COMMIT")

        remaining = conn.execute(
            "SELECT COUNT(*) FROM execution_custom_field_values WHERE execution_id = 'E1'"
        ).fetchone()[0]
        assert remaining == 0
    finally:
        conn.close()


def test_execution_custom_field_values_cascade_on_field_delete():
    conn = _fresh_db()
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit, position_after,"
            " source_order_id, source_filename, imported_at) VALUES "
            "('E2', 'Sim', 'MES', 1700000001, 'Buy', 'Buy', 1, 4500.0, 2.50, 'Entry', 1, 'O', 'f.csv', 1700000001)"
        )
        conn.execute(
            "INSERT INTO custom_fields (name, field_type, created_at) VALUES ('confidence', 'number', 0)"
        )
        fid = conn.execute("SELECT field_id FROM custom_fields WHERE name='confidence'").fetchone()[
            0
        ]
        conn.execute(
            "INSERT INTO execution_custom_field_values (execution_id, field_id, value, updated_at) "
            "VALUES ('E2', ?, '4.0', 0)",
            (fid,),
        )
        conn.execute("COMMIT")

        conn.execute("BEGIN")
        conn.execute("DELETE FROM custom_fields WHERE field_id = ?", (fid,))
        conn.execute("COMMIT")

        remaining = conn.execute(
            "SELECT COUNT(*) FROM execution_custom_field_values WHERE field_id = ?", (fid,)
        ).fetchone()[0]
        assert remaining == 0
    finally:
        conn.close()
