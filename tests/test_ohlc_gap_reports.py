from pathlib import Path

from db import connect
from migrations import run_migrations
from services.ohlc.gap_reports import (
    compute_backoff,
    list_open,
    record_retry_outcome,
    reset_for_retry,
    select_due,
    update_gap_reports,
)


ONE_HOUR = 3600


def _fresh_conn(tmp_path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def _insert_bar(conn, *, instrument, timeframe, ts, source="yfinance"):
    conn.execute(
        "INSERT OR REPLACE INTO bars"
        " (instrument, timeframe, time, open, high, low, close, volume, source, fetched_at)"
        " VALUES (?, ?, ?, 1, 1, 1, 1, 0, ?, ?)",
        (instrument, timeframe, ts, source, ts),
    )


def test_compute_backoff_doubles_then_caps():
    assert compute_backoff(1) == 3600
    assert compute_backoff(2) == 2 * 3600
    assert compute_backoff(3) == 4 * 3600
    assert compute_backoff(5) == 16 * 3600
    assert compute_backoff(6) == 24 * 3600  # capped
    assert compute_backoff(20) == 24 * 3600


def test_update_gap_reports_skips_gaps_younger_than_one_hour(tmp_path):
    """A gap whose gap_end is less than 1h ago must NOT be reported."""
    conn = _fresh_conn(tmp_path)
    now = 10 * 86400
    end = now - 1800
    start = end - 600
    update_gap_reports(
        conn,
        instrument="MNQ",
        timeframe="1m",
        range_start=start,
        range_end=end,
        attempt_id=None,
        now=now,
    )
    reports = list_open(conn)
    assert reports == []


def test_update_gap_reports_records_gaps_older_than_one_hour(tmp_path):
    conn = _fresh_conn(tmp_path)
    # Tue 1970-01-13 18:00 UTC — the window (16:00 UTC = 10:00 CT) is
    # in-session on a weekday, clear of the weekend closure and daily break.
    now = 12 * 86400 + 18 * ONE_HOUR
    end = now - 2 * ONE_HOUR  # the whole window is > 1h in the past
    start = end - 600  # 10 x 1m slots, none inserted -> all gaps
    update_gap_reports(
        conn,
        instrument="MNQ",
        timeframe="1m",
        range_start=start,
        range_end=end,
        attempt_id=None,
        now=now,
    )
    reports = list_open(conn)
    assert len(reports) == 1
    r = reports[0]
    assert r["instrument"] == "MNQ"
    assert r["timeframe"] == "1m"
    assert r["gap_start"] == start
    assert r["gap_end"] == end
    assert r["state"] == "open"
    assert r["attempt_count"] == 0
    assert r["next_retry_at"] == now  # first scheduling is immediate


def test_update_gap_reports_marks_filled_gap_resolved(tmp_path):
    conn = _fresh_conn(tmp_path)
    now = 12 * 86400 + 18 * ONE_HOUR  # in-session weekday window (see above)
    end = now - 2 * ONE_HOUR
    start = end - 600
    # First pass: no bars — gap recorded.
    update_gap_reports(
        conn,
        instrument="MNQ",
        timeframe="1m",
        range_start=start,
        range_end=end,
        attempt_id=None,
        now=now,
    )
    assert len(list_open(conn)) == 1
    # Fill in every minute slot (10 of them).
    for i in range(10):
        _insert_bar(conn, instrument="MNQ", timeframe="1m", ts=start + i * 60)
    # Second pass: gap now covered.
    update_gap_reports(
        conn,
        instrument="MNQ",
        timeframe="1m",
        range_start=start,
        range_end=end,
        attempt_id=None,
        now=now + 100,
    )
    assert list_open(conn) == []
    resolved = conn.execute(
        "SELECT * FROM ohlc_gap_reports WHERE state='resolved'"
    ).fetchone()
    assert resolved["resolved_at"] == now + 100


def test_select_due_respects_next_retry_at_and_limit(tmp_path):
    conn = _fresh_conn(tmp_path)
    now = 10 * 86400
    # Seed 3 gap-report rows directly.
    for i in range(3):
        conn.execute(
            "INSERT INTO ohlc_gap_reports"
            " (instrument, timeframe, gap_start, gap_end, first_seen_at,"
            "  attempt_count, next_retry_at, state)"
            " VALUES (?, '1m', ?, ?, ?, 0, ?, 'open')",
            (f"I{i}", i * 60, (i + 1) * 60, now - 7200, now - 10 + i),
        )
    rows = select_due(conn, now=now, limit=2)
    assert len(rows) == 2


def test_select_due_ignores_future_retries(tmp_path):
    conn = _fresh_conn(tmp_path)
    now = 10 * 86400
    conn.execute(
        "INSERT INTO ohlc_gap_reports"
        " (instrument, timeframe, gap_start, gap_end, first_seen_at,"
        "  attempt_count, next_retry_at, state)"
        " VALUES ('MNQ', '1m', 0, 60, ?, 0, ?, 'open')",
        (now - 7200, now + 3600),
    )
    assert select_due(conn, now=now, limit=10) == []


def _seed_attempt(conn, aid, *, started_at=0):
    conn.execute(
        "INSERT INTO fetch_attempts (id, trigger, instrument, timeframe,"
        " range_start, range_end, started_at)"
        " VALUES (?, 'test', 'MNQ', '1m', 0, 60, ?)",
        (aid, started_at),
    )


def test_record_retry_outcome_increments_and_backs_off(tmp_path):
    conn = _fresh_conn(tmp_path)
    now = 10 * 86400
    _seed_attempt(conn, "abc")
    conn.execute(
        "INSERT INTO ohlc_gap_reports"
        " (instrument, timeframe, gap_start, gap_end, first_seen_at,"
        "  attempt_count, next_retry_at, state)"
        " VALUES ('MNQ', '1m', 0, 60, ?, 0, ?, 'open')",
        (now - 7200, now - 10),
    )
    row = conn.execute("SELECT id FROM ohlc_gap_reports").fetchone()
    record_retry_outcome(
        conn, gap_id=row["id"], attempt_id="abc", resolved=False, now=now,
    )
    r = conn.execute(
        "SELECT * FROM ohlc_gap_reports WHERE id=?", (row["id"],)
    ).fetchone()
    assert r["attempt_count"] == 1
    assert r["last_attempt_id"] == "abc"
    assert r["last_attempt_at"] == now
    assert r["next_retry_at"] == now + compute_backoff(1)
    assert r["state"] == "open"


def test_record_retry_outcome_abandons_after_threshold(tmp_path):
    conn = _fresh_conn(tmp_path)
    now = 10 * 86400
    _seed_attempt(conn, "abc")
    conn.execute(
        "INSERT INTO ohlc_gap_reports"
        " (instrument, timeframe, gap_start, gap_end, first_seen_at,"
        "  attempt_count, next_retry_at, state)"
        " VALUES ('MNQ', '1m', 0, 60, ?, 9, ?, 'open')",
        (now - 7200, now - 10),
    )
    row = conn.execute("SELECT id FROM ohlc_gap_reports").fetchone()
    record_retry_outcome(
        conn, gap_id=row["id"], attempt_id="abc", resolved=False, now=now,
    )
    r = conn.execute(
        "SELECT state FROM ohlc_gap_reports WHERE id=?", (row["id"],)
    ).fetchone()
    assert r["state"] == "abandoned"


def test_reset_for_retry_reopens_abandoned(tmp_path):
    conn = _fresh_conn(tmp_path)
    now = 10 * 86400
    conn.execute(
        "INSERT INTO ohlc_gap_reports"
        " (instrument, timeframe, gap_start, gap_end, first_seen_at,"
        "  attempt_count, next_retry_at, state)"
        " VALUES ('MNQ', '1m', 0, 60, ?, 10, ?, 'abandoned')",
        (now - 7200, now + 3600),
    )
    row = conn.execute("SELECT id FROM ohlc_gap_reports").fetchone()
    reset_for_retry(conn, gap_id=row["id"], now=now)
    r = conn.execute(
        "SELECT * FROM ohlc_gap_reports WHERE id=?", (row["id"],)
    ).fetchone()
    assert r["state"] == "open"
    assert r["attempt_count"] == 0
    assert r["next_retry_at"] == now
