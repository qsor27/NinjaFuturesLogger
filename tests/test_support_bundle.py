import sqlite3
from pathlib import Path

from db import connect
from migrations import run_migrations
from services.support_bundle import snapshot_db


def _init_db(tmp_path: Path) -> Path:
    db = tmp_path / "trading_log.db"
    conn = connect(db)
    try:
        run_migrations(conn, Path("migrations"))
        conn.commit()
    finally:
        conn.close()
    return db


def test_snapshot_db_empty_returns_all_expected_keys(tmp_path: Path):
    db = _init_db(tmp_path)
    snap = snapshot_db(db, days=7, now=1_700_000_000)

    assert set(snap.keys()) == {
        "fetch_attempts",
        "fetch_source_attempts",
        "ohlc_gap_reports",
        "ohlc_breaker_state",
        "import_runs",
        "import_rejects",
        "integrity_issues",
        "schema_migrations",
    }
    for rows in snap.values():
        assert isinstance(rows, list)
    # schema_migrations has at least one row after run_migrations
    assert len(snap["schema_migrations"]) >= 1


def test_snapshot_db_windows_by_days(tmp_path: Path):
    db = _init_db(tmp_path)
    now = 1_700_000_000
    cutoff = now - 7 * 86400

    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO fetch_attempts"
        " (id, trigger, instrument, timeframe, range_start, range_end,"
        "  started_at, gaps_found, bars_written, final_status)"
        " VALUES (?, 'on_demand', 'MNQ', '1m', 0, 0, ?, 0, 0, 'ok')",
        ("keep", cutoff + 100),
    )
    conn.execute(
        "INSERT INTO fetch_attempts"
        " (id, trigger, instrument, timeframe, range_start, range_end,"
        "  started_at, gaps_found, bars_written, final_status)"
        " VALUES (?, 'on_demand', 'MNQ', '1m', 0, 0, ?, 0, 0, 'ok')",
        ("drop", cutoff - 100),
    )
    conn.commit()
    conn.close()

    snap = snapshot_db(db, days=7, now=now)
    ids = {row["id"] for row in snap["fetch_attempts"]}
    assert ids == {"keep"}


def test_snapshot_db_caps_row_count(tmp_path: Path):
    db = _init_db(tmp_path)
    now = 1_700_000_000
    conn = sqlite3.connect(db)
    for i in range(10_100):
        conn.execute(
            "INSERT INTO fetch_attempts"
            " (id, trigger, instrument, timeframe, range_start, range_end,"
            "  started_at, gaps_found, bars_written, final_status)"
            " VALUES (?, 'sweep', 'MNQ', '1m', 0, 0, ?, 0, 0, 'ok')",
            (f"a{i}", now - i),
        )
    conn.commit()
    conn.close()

    snap = snapshot_db(db, days=7, now=now)
    assert len(snap["fetch_attempts"]) == 10_000
    # Most-recent first: the newest 10k rows kept, older 100 dropped.
    ids = [r["id"] for r in snap["fetch_attempts"]]
    assert "a0" in ids
    assert "a10099" not in ids
