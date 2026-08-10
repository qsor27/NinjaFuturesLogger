import sqlite3

import pytest

from db import connect
from tests.conftest import make_execution, seed_executions


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_review_tables_exist(migrated_db):
    conn = connect(migrated_db)
    try:
        assert _columns(conn, "review_sessions") == ["session_id", "started_at", "ended_at"]
        assert _columns(conn, "review_attempts") == [
            "attempt_id",
            "session_id",
            "account",
            "instrument",
            "entry_execution_id",
            "real_execution_id",
            "call",
            "outcome_pnl",
            "created_at",
        ]
    finally:
        conn.close()


def test_attempt_call_is_checked(migrated_db):
    seed_executions(migrated_db, [make_execution("e1")])
    conn = connect(migrated_db)
    try:
        conn.execute("INSERT INTO review_sessions (started_at) VALUES (1)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO review_attempts (session_id, account, instrument,"
                " entry_execution_id, real_execution_id, call, outcome_pnl, created_at)"
                " VALUES (1, 'Sim101', 'MNQ', 'e1', 'e1', 'maybe', 0.0, 1)"
            )
    finally:
        conn.close()


def test_execution_rollback_cascades_attempts(migrated_db):
    seed_executions(migrated_db, [make_execution("e1")])
    conn = connect(migrated_db)
    try:
        conn.execute("INSERT INTO review_sessions (started_at) VALUES (1)")
        conn.execute(
            "INSERT INTO review_attempts (session_id, account, instrument,"
            " entry_execution_id, real_execution_id, call, outcome_pnl, created_at)"
            " VALUES (1, 'Sim101', 'MNQ', 'e1#open', 'e1', 'valid', 12.5, 1)"
        )
        conn.commit()
        conn.execute("DELETE FROM executions WHERE nt_execution_id = 'e1'")
        conn.commit()
        rows = conn.execute("SELECT COUNT(*) FROM review_attempts").fetchone()[0]
        assert rows == 0
    finally:
        conn.close()
