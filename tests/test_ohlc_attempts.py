import sqlite3
from pathlib import Path

from db import connect
from migrations import run_migrations
from services.ohlc.attempts import (
    begin_attempt,
    complete_attempt,
    new_attempt_id,
    orphan_sweep,
    record_source_attempt,
    trim_older_than,
)


def _fresh_conn(tmp_path) -> sqlite3.Connection:
    db = tmp_path / "t.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    return conn


def test_migration_011_creates_all_four_tables(tmp_path):
    db = tmp_path / "t.db"
    conn = connect(db)
    try:
        run_migrations(conn, Path("migrations"))
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    for expected in (
        "fetch_attempts",
        "fetch_source_attempts",
        "ohlc_gap_reports",
        "ohlc_breaker_state",
    ):
        assert expected in tables, f"missing table: {expected}"


def test_new_attempt_id_is_unique_and_nonempty():
    ids = {new_attempt_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(isinstance(x, str) and len(x) > 0 for x in ids)


def test_begin_complete_attempt_roundtrip(tmp_path):
    conn = _fresh_conn(tmp_path)
    aid = new_attempt_id()
    begin_attempt(
        conn,
        attempt_id=aid,
        trigger="maintainer",
        instrument="MNQ",
        timeframe="1m",
        range_start=1000,
        range_end=2000,
        now=1500,
    )
    complete_attempt(
        conn,
        attempt_id=aid,
        now=1600,
        gaps_found=2,
        bars_written=50,
        final_status="ok",
        error=None,
    )
    row = conn.execute("SELECT * FROM fetch_attempts WHERE id = ?", (aid,)).fetchone()
    assert row["trigger"] == "maintainer"
    assert row["started_at"] == 1500
    assert row["completed_at"] == 1600
    assert row["gaps_found"] == 2
    assert row["bars_written"] == 50
    assert row["final_status"] == "ok"


def test_record_source_attempt_rows(tmp_path):
    conn = _fresh_conn(tmp_path)
    aid = new_attempt_id()
    begin_attempt(
        conn,
        attempt_id=aid,
        trigger="on_demand",
        instrument="MNQ",
        timeframe="5m",
        range_start=1000,
        range_end=2000,
        now=1500,
    )
    record_source_attempt(
        conn,
        attempt_id=aid,
        gap_start=1000,
        gap_end=1200,
        source="yfinance",
        outcome="ok",
        bars_returned=40,
        duration_ms=312,
        http_status=200,
        error_class=None,
        error=None,
    )
    record_source_attempt(
        conn,
        attempt_id=aid,
        gap_start=1200,
        gap_end=2000,
        source="yfinance",
        outcome="skipped_breaker",
        bars_returned=0,
        duration_ms=0,
        http_status=None,
        error_class=None,
        error=None,
    )
    rows = conn.execute(
        "SELECT * FROM fetch_source_attempts WHERE attempt_id = ? ORDER BY id",
        (aid,),
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["outcome"] == "ok"
    assert rows[0]["bars_returned"] == 40
    assert rows[1]["outcome"] == "skipped_breaker"


def test_orphan_sweep_closes_dangling_attempts(tmp_path):
    conn = _fresh_conn(tmp_path)
    aid = new_attempt_id()
    begin_attempt(
        conn,
        attempt_id=aid,
        trigger="maintainer",
        instrument="MNQ",
        timeframe="1m",
        range_start=0,
        range_end=60,
        now=100,
    )
    # Do not complete_attempt; simulate a crash.
    closed = orphan_sweep(conn, now=200)
    assert closed == 1
    row = conn.execute(
        "SELECT final_status, completed_at, error FROM fetch_attempts WHERE id=?",
        (aid,),
    ).fetchone()
    assert row["final_status"] == "interrupted"
    assert row["completed_at"] == 200
    assert row["error"] == "process restarted while running"


def test_trim_older_than_cascades(tmp_path):
    conn = _fresh_conn(tmp_path)
    old = new_attempt_id()
    young = new_attempt_id()
    begin_attempt(
        conn,
        attempt_id=old,
        trigger="maintainer",
        instrument="MNQ",
        timeframe="1m",
        range_start=0,
        range_end=60,
        now=1000,
    )
    complete_attempt(
        conn,
        attempt_id=old,
        now=1001,
        gaps_found=0,
        bars_written=0,
        final_status="cached",
        error=None,
    )
    record_source_attempt(
        conn,
        attempt_id=old,
        gap_start=0,
        gap_end=60,
        source="yfinance",
        outcome="ok",
        bars_returned=0,
        duration_ms=10,
        http_status=200,
        error_class=None,
        error=None,
    )
    begin_attempt(
        conn,
        attempt_id=young,
        trigger="on_demand",
        instrument="MNQ",
        timeframe="1m",
        range_start=60,
        range_end=120,
        now=9999,
    )
    complete_attempt(
        conn,
        attempt_id=young,
        now=10000,
        gaps_found=0,
        bars_written=0,
        final_status="cached",
        error=None,
    )
    deleted = trim_older_than(conn, cutoff=5000)
    assert deleted == 1
    remaining = conn.execute("SELECT id FROM fetch_attempts").fetchall()
    assert [r["id"] for r in remaining] == [young]
    # Cascade — no orphan source-attempts
    orphan = conn.execute(
        "SELECT COUNT(*) AS c FROM fetch_source_attempts WHERE attempt_id=?",
        (old,),
    ).fetchone()
    assert orphan["c"] == 0
