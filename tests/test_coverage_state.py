from pathlib import Path

from db import connect
from migrations import run_migrations
from services.ohlc.coverage_state import (
    list_coverage,
    reactivate,
    refresh_instrument_coverage_state,
    retire_now,
    set_pinned,
)


def _setup(tmp_path):
    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    return conn


def _insert_execution(conn, *, nt_id, account, instrument, ts):
    conn.execute(
        "INSERT INTO executions (nt_execution_id, account, instrument, timestamp,"
        " side, original_action, quantity, price, commission, entry_exit,"
        " source_filename, imported_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            nt_id,
            account,
            instrument,
            ts,
            "Buy",
            "Buy",
            1,
            100.0,
            0.0,
            "Entry",
            "test.csv",
            ts,
        ),
    )


def test_new_execution_creates_active_row(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(conn, nt_id="e1", account="sim", instrument="MNQ JUN26", ts=now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    rows = list_coverage(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r.instrument == "MNQ JUN26"
    assert r.state == "active"
    assert r.last_execution_at == now - 3600


def test_old_execution_becomes_winding_down(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(
        conn,
        nt_id="e1",
        account="sim",
        instrument="MNQ MAR26",
        ts=now - 40 * 86400,
    )
    refresh_instrument_coverage_state(conn, now=now)
    assert list_coverage(conn)[0].state == "winding_down"


def test_pinned_overrides_inactivity(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(
        conn,
        nt_id="e1",
        account="sim",
        instrument="MNQ MAR26",
        ts=now - 100 * 86400,
    )
    refresh_instrument_coverage_state(conn, now=now)
    set_pinned(conn, instrument="MNQ MAR26", pinned=True, now=now)
    refresh_instrument_coverage_state(conn, now=now)
    assert list_coverage(conn)[0].state == "active"


def test_retire_now_jumps_to_retired(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(conn, nt_id="e1", account="sim", instrument="CL JUL26", ts=now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    retire_now(conn, instrument="CL JUL26", now=now)
    rows = list_coverage(conn)
    assert rows[0].state == "retired"
    refresh_instrument_coverage_state(conn, now=now)
    assert list_coverage(conn)[0].state == "retired"


def test_reactivate_brings_back_to_active(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(conn, nt_id="e1", account="sim", instrument="CL JUL26", ts=now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    retire_now(conn, instrument="CL JUL26", now=now)
    reactivate(conn, instrument="CL JUL26", now=now)
    refresh_instrument_coverage_state(conn, now=now)
    assert list_coverage(conn)[0].state == "active"


def test_180_day_safety_backstop(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(
        conn,
        nt_id="e1",
        account="sim",
        instrument="MNQ SEP25",
        ts=now - 200 * 86400,
    )
    refresh_instrument_coverage_state(conn, now=now)
    assert list_coverage(conn)[0].state == "retired"
