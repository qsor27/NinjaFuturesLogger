from pathlib import Path

from db import connect
from migrations import run_migrations


def test_008_creates_instrument_coverage_table(tmp_path):
    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(instrument_coverage)").fetchall()}
    assert cols == {
        "instrument",
        "state",
        "last_execution_at",
        "pinned",
        "retired_at",
        "updated_at",
    }


def test_008_state_check_constraint(tmp_path):
    import sqlite3

    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    conn.execute(
        "INSERT INTO instrument_coverage (instrument, state, pinned, updated_at)"
        " VALUES (?, ?, 0, 0)",
        ("MNQ JUN26", "active"),
    )
    try:
        conn.execute(
            "INSERT INTO instrument_coverage (instrument, state, pinned, updated_at)"
            " VALUES (?, ?, 0, 0)",
            ("ES MAR26", "bogus"),
        )
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised
