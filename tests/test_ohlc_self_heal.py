from pathlib import Path

from db import connect
from migrations import run_migrations
from services.ohlc.self_heal import self_heal_tick


def _fresh_db(tmp_path):
    db = tmp_path / "t.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    conn.close()
    return db


def test_self_heal_tick_retries_due_rows(tmp_path):
    db = _fresh_db(tmp_path)
    now = 10 * 86400
    conn = connect(db)
    conn.execute(
        "INSERT INTO ohlc_gap_reports"
        " (instrument, timeframe, gap_start, gap_end, first_seen_at,"
        "  attempt_count, next_retry_at, state)"
        " VALUES ('MNQ', '1m', 0, 60, ?, 0, ?, 'open')",
        (now - 7200, now - 10),
    )
    conn.commit()
    conn.close()

    calls = []

    def fake_fetch(*, db_path, instrument, timeframe, start, end, trigger):
        calls.append((instrument, timeframe, start, end, trigger))
        # Pretend the retry didn't actually fill the gap — the row stays open.

    self_heal_tick(db_path=db, fetch_fn=fake_fetch, now=now, limit=10)

    assert calls == [("MNQ", "1m", 0, 60, "self_heal")]

    conn = connect(db)
    r = conn.execute("SELECT * FROM ohlc_gap_reports").fetchone()
    conn.close()
    assert r["attempt_count"] == 1
    assert r["next_retry_at"] == now + 3600  # compute_backoff(1)


def test_self_heal_tick_marks_resolved_when_gap_is_now_filled(tmp_path):
    db = _fresh_db(tmp_path)
    now = 10 * 86400
    conn = connect(db)
    conn.execute(
        "INSERT INTO ohlc_gap_reports"
        " (instrument, timeframe, gap_start, gap_end, first_seen_at,"
        "  attempt_count, next_retry_at, state)"
        " VALUES ('MNQ', '1m', 0, 60, ?, 0, ?, 'open')",
        (now - 7200, now - 10),
    )
    conn.commit()
    conn.close()

    def fake_fetch(*, db_path, instrument, timeframe, start, end, trigger):
        # Simulate a successful fetch — insert the missing bar.
        c = connect(db_path)
        c.execute(
            "INSERT INTO bars (instrument, timeframe, time, open, high, low,"
            " close, volume, source, fetched_at)"
            " VALUES (?, ?, ?, 1, 1, 1, 1, 0, 'fake', ?)",
            (instrument, timeframe, start, start),
        )
        c.close()

    self_heal_tick(db_path=db, fetch_fn=fake_fetch, now=now, limit=10)

    conn = connect(db)
    r = conn.execute("SELECT * FROM ohlc_gap_reports").fetchone()
    conn.close()
    assert r["state"] == "resolved"
    assert r["resolved_at"] == now


def test_self_heal_tick_respects_limit(tmp_path):
    db = _fresh_db(tmp_path)
    now = 10 * 86400
    conn = connect(db)
    for i in range(5):
        conn.execute(
            "INSERT INTO ohlc_gap_reports"
            " (instrument, timeframe, gap_start, gap_end, first_seen_at,"
            "  attempt_count, next_retry_at, state)"
            " VALUES (?, '1m', ?, ?, ?, 0, ?, 'open')",
            (f"I{i}", i * 60, (i + 1) * 60, now - 7200, now - 10 + i),
        )
    conn.commit()
    conn.close()

    calls = []

    def fake_fetch(**kw):
        calls.append(kw["instrument"])

    self_heal_tick(db_path=db, fetch_fn=fake_fetch, now=now, limit=2)
    assert len(calls) == 2
