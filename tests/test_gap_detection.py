from datetime import UTC, datetime

from db import connect
from models.bar import Bar
from services.ohlc.gap_detection import find_gaps, timeframe_seconds
from services.ohlc.store import insert_many


def _t(s: str) -> int:
    """UTC ISO -> unix seconds."""
    return int(datetime.fromisoformat(s).replace(tzinfo=UTC).timestamp())


def test_timeframe_seconds_table():
    assert timeframe_seconds("1m") == 60
    assert timeframe_seconds("5m") == 300
    assert timeframe_seconds("15m") == 900
    assert timeframe_seconds("1h") == 3600
    assert timeframe_seconds("4h") == 14400
    assert timeframe_seconds("1d") == 86400


def test_no_bars_returns_full_range_during_session(migrated_db):
    """An empty store should yield one gap covering the whole session window."""
    conn = connect(migrated_db)
    try:
        # 22:00 UTC = 17:00 America/Chicago = session open
        start = _t("2026-04-13T22:01:00")
        end = _t("2026-04-13T22:06:00")
        gaps = find_gaps(conn, instrument="MNQ", timeframe="1m", start=start, end=end)
    finally:
        conn.close()
    assert gaps == [(start, end)]


def test_full_coverage_returns_empty(migrated_db):
    conn = connect(migrated_db)
    try:
        start = _t("2026-04-13T22:01:00")
        end = _t("2026-04-13T22:04:00")
        bars = [
            Bar(
                instrument="MNQ",
                timeframe="1m",
                time=t,
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=0,
                source="t",
            )
            for t in range(start, end, 60)
        ]
        insert_many(conn, bars)
        gaps = find_gaps(conn, instrument="MNQ", timeframe="1m", start=start, end=end)
    finally:
        conn.close()
    assert gaps == []


def test_single_missing_run_in_middle(migrated_db):
    conn = connect(migrated_db)
    try:
        start = _t("2026-04-13T22:01:00")
        end = _t("2026-04-13T22:06:00")
        present_times = [start, start + 60, start + 240]  # missing 120, 180
        bars = [
            Bar(
                instrument="MNQ",
                timeframe="1m",
                time=t,
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=0,
                source="t",
            )
            for t in present_times
        ]
        insert_many(conn, bars)
        gaps = find_gaps(conn, instrument="MNQ", timeframe="1m", start=start, end=end)
    finally:
        conn.close()
    assert gaps == [(start + 120, start + 240)]


def test_skips_daily_break(migrated_db):
    """No gap should be reported during the 16:00–17:00 America/Chicago break."""
    conn = connect(migrated_db)
    try:
        # 21:00–22:00 UTC = 16:00–17:00 America/Chicago = daily break
        start = _t("2026-04-13T21:00:00")
        end = _t("2026-04-13T22:00:00")
        gaps = find_gaps(conn, instrument="MNQ", timeframe="1m", start=start, end=end)
    finally:
        conn.close()
    assert gaps == []


def test_no_gap_reported_over_weekend_closure(migrated_db):
    """CME is closed from Friday 16:00 CT to Sunday 17:00 CT. Intraday
    timeframes must not report that span as missing bars — no provider
    will ever have data there."""
    conn = connect(migrated_db)
    try:
        # Fri 2026-04-17 21:00 UTC = 16:00 CT (close) → Sun 2026-04-19
        # 22:00 UTC = 17:00 CT (reopen).
        start = _t("2026-04-17T21:00:00")
        end = _t("2026-04-19T22:00:00")
        gaps = find_gaps(conn, instrument="MNQ", timeframe="1h", start=start, end=end)
    finally:
        conn.close()
    assert gaps == []


def test_friday_and_sunday_session_hours_still_expected():
    """Weekend skipping must not swallow real session hours on its edges."""
    from services.ohlc.gap_detection import expected_session_slots

    # Friday 14:00–16:00 CT (19:00–21:00 UTC) is in-session.
    fri = expected_session_slots(
        "MNQ", "1h", _t("2026-04-17T19:00:00"), _t("2026-04-17T21:00:00")
    )
    assert fri == [_t("2026-04-17T19:00:00"), _t("2026-04-17T20:00:00")]

    # Sunday 17:00–18:00 CT (22:00–23:00 UTC) is in-session (post-reopen).
    sun = expected_session_slots(
        "MNQ", "1h", _t("2026-04-19T22:00:00"), _t("2026-04-19T23:00:00")
    )
    assert sun == [_t("2026-04-19T22:00:00")]


def test_classify_window_marks_slots_beyond_reach_as_out_of_reach(tmp_path):
    from pathlib import Path

    from db import connect
    from migrations import run_migrations
    from services.ohlc.gap_detection import classify_window

    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    now = 1_000_000_000
    # 1m reach is 30 days; ask for a 60-day window so half is out of reach.
    summary = classify_window(
        conn,
        instrument="MNQ JUN26",
        timeframe="1m",
        start=now - 60 * 86400,
        end=now,
        now=now,
    )
    assert summary["expected"] > 0
    assert summary["present"] == 0
    assert summary["out_of_reach"] > 0
    assert summary["missing"] > 0
    reachable = summary["expected"] - summary["out_of_reach"]
    # ~30 days of session minutes minus the daily break and the weekend
    # closures (Fri close → Sun open) — roughly 29k slots.
    assert 25_000 < reachable < 33_000


def test_classify_window_matches_1d_bars_at_utc_midnight(tmp_path):
    """yfinance stamps daily bars at 00:00 UTC but the session-aware walker
    emits slots at 17:00 CT. classify_window must bucket both sides to a
    UTC calendar day so present bars actually match expected slots."""
    from pathlib import Path

    from db import connect
    from migrations import run_migrations
    from services.ohlc.gap_detection import classify_window

    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    base_utc_midnight = 1776124800  # 2026-04-14T00:00:00Z
    for i in range(5):
        conn.execute(
            "INSERT INTO bars (instrument, timeframe, time, open, high, low, close,"
            " volume, source, fetched_at)"
            " VALUES ('MNQ JUN26', '1d', ?, 1, 2, 0, 1, 100, 'yfinance', 0)",
            (base_utc_midnight - i * 86400,),
        )
    now = base_utc_midnight + 86400
    summary = classify_window(
        conn,
        instrument="MNQ JUN26",
        timeframe="1d",
        start=base_utc_midnight - 4 * 86400,
        end=now,
        now=now,
    )
    # Apr 10–14 2026 spans a weekend (Sat Apr 11, Sun Apr 12); the walker
    # only expects Mon–Fri slots for 1d, so 3 of the 5 inserted bars map to
    # an expected slot. The point this test guards is that UTC-midnight
    # stamped bars *do* get matched — not the weekday count itself.
    assert summary["present"] == 3
    assert summary["missing"] == 0
