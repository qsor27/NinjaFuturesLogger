from pathlib import Path

from db import connect


def test_connect_enables_wal_and_foreign_keys(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
        assert journal_mode.lower() == "wal"
        assert fk == 1
        assert synchronous == 1  # NORMAL
    finally:
        conn.close()


def test_connect_creates_parent_dir(tmp_path: Path):
    target = tmp_path / "nested" / "dir" / "t.db"
    conn = connect(target)
    try:
        assert target.exists()
    finally:
        conn.close()
