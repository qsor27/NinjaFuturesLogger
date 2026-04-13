from pathlib import Path

from db import connect
from migrations import applied_versions, run_migrations


def _migrate(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def test_004_is_applied(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        assert "004_bars" in applied_versions(conn)
    finally:
        conn.close()


def test_bars_columns(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(bars)").fetchall()}
        assert cols == {
            "instrument",
            "timeframe",
            "time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
            "fetched_at",
        }
    finally:
        conn.close()


def test_bars_primary_key_is_composite(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        rows = conn.execute("PRAGMA table_info(bars)").fetchall()
        pk_cols = sorted([r[1] for r in rows if r[5] > 0], key=lambda c: c)
        assert pk_cols == ["instrument", "time", "timeframe"]
    finally:
        conn.close()


def test_bars_has_lookup_index(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master " "WHERE type='index' AND tbl_name='bars'"
            ).fetchall()
        }
        assert "idx_bars_instrument_tf_time" in names
    finally:
        conn.close()


def test_no_foreign_keys_to_bars(tmp_path: Path):
    """Rule 6 from doc 14 — bars must not be referenced by any other table."""
    conn = _migrate(tmp_path)
    try:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        for tbl in tables:
            for fk in conn.execute(f"PRAGMA foreign_key_list({tbl})").fetchall():
                assert fk[2] != "bars", f"{tbl} has a FK to bars"
    finally:
        conn.close()
