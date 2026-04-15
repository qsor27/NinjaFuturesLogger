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


def test_classify_window_marks_slots_beyond_reach_as_out_of_reach(tmp_path):
    from pathlib import Path

    from db import connect
    from migrations import run_migrations
    from services.ohlc.gap_detection import classify_window

    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    now = 1_000_000_000
    summary = classify_window(
        conn,
        instrument="MNQ JUN26",
        timeframe="1m",
        start=now - 30 * 86400,
        end=now,
        now=now,
    )
    assert summary["expected"] > 0
    assert summary["present"] == 0
    assert summary["out_of_reach"] > 0
    assert summary["missing"] > 0
    reachable = summary["expected"] - summary["out_of_reach"]
    assert 4000 < reachable < 12000
