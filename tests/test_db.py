import sqlite3
from pathlib import Path

import pytest

from db import connect, read_conn, sql_placeholders, transaction


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


def test_transaction_commits_on_success(tmp_path: Path):
    db_path = tmp_path / "t.db"
    with transaction(db_path) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t (x) VALUES (1)")
    check = connect(db_path)
    try:
        assert check.execute("SELECT x FROM t").fetchone()[0] == 1
    finally:
        check.close()


def test_transaction_rolls_back_on_exception(tmp_path: Path):
    db_path = tmp_path / "t.db"
    with transaction(db_path) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(RuntimeError):
        with transaction(db_path) as conn:
            conn.execute("INSERT INTO t (x) VALUES (1)")
            raise RuntimeError("boom")
    check = connect(db_path)
    try:
        assert check.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    finally:
        check.close()


def test_transaction_closes_connection(tmp_path: Path):
    db_path = tmp_path / "t.db"
    with transaction(db_path) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_read_conn_yields_row_conn_and_closes(tmp_path: Path):
    db_path = tmp_path / "t.db"
    with transaction(db_path) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t (x) VALUES (7)")
    with read_conn(db_path) as conn:
        row = conn.execute("SELECT x FROM t").fetchone()
        assert row["x"] == 7  # Row factory preserved
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_sql_placeholders():
    assert sql_placeholders(0) == ""
    assert sql_placeholders(1) == "?"
    assert sql_placeholders(3) == "?,?,?"
