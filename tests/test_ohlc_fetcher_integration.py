from pathlib import Path

from db import connect
from migrations import run_migrations
from models.bar import Bar
from services.ohlc.fetcher import fetch_range
from services.ohlc.registry import SourceRegistry


class _GoodSource:
    name = "good"
    supported_timeframes = frozenset({"1m"})

    def __init__(self, bars):
        self._bars = bars
        self.calls = 0

    def fetch(self, instrument, timeframe, start, end):
        self.calls += 1
        return [
            Bar(
                instrument=instrument,
                timeframe=timeframe,
                time=t,
                open=1,
                high=1,
                low=1,
                close=1,
                volume=0,
                source="good",
            )
            for t in self._bars
            if start <= t < end
        ]


class _BadSource:
    name = "bad"
    supported_timeframes = frozenset({"1m"})

    def fetch(self, instrument, timeframe, start, end):
        raise RuntimeError("boom")


def _make_registry(*sources, clock):
    reg = SourceRegistry(clock=clock)
    for s in sources:
        reg.register(
            s,
            failure_threshold=3,
            base_cooldown_seconds=60,
        )
    return reg


def _fresh_db(tmp_path):
    db = tmp_path / "t.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    conn.close()
    return db


def test_fetch_range_writes_attempt_row(tmp_path):
    db = _fresh_db(tmp_path)
    bars = [i * 60 for i in range(10)]
    reg = _make_registry(_GoodSource(bars), clock=lambda: 10_000)
    result = fetch_range(
        db_path=db,
        registry=reg,
        instrument="MNQ",
        timeframe="1m",
        start=0,
        end=600,
        trigger="maintainer",
    )
    assert result.attempt_id != ""
    conn = connect(db)
    row = conn.execute(
        "SELECT * FROM fetch_attempts WHERE id = ?",
        (result.attempt_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["trigger"] == "maintainer"
    assert row["instrument"] == "MNQ"
    assert row["timeframe"] == "1m"
    assert row["final_status"] is not None
    assert row["completed_at"] is not None


def test_fetch_range_records_source_attempts_including_failures(tmp_path):
    db = _fresh_db(tmp_path)
    bars = [i * 60 for i in range(5)]
    reg = _make_registry(
        _BadSource(),
        _GoodSource(bars),
        clock=lambda: 10_000,
    )
    result = fetch_range(
        db_path=db,
        registry=reg,
        instrument="MNQ",
        timeframe="1m",
        start=0,
        end=300,
        trigger="on_demand",
    )
    conn = connect(db)
    rows = conn.execute(
        "SELECT source, outcome, bars_returned FROM fetch_source_attempts"
        " WHERE attempt_id = ? ORDER BY id",
        (result.attempt_id,),
    ).fetchall()
    conn.close()
    assert ("bad", "failed") in [(r["source"], r["outcome"]) for r in rows]
    assert ("good", "ok") in [(r["source"], r["outcome"]) for r in rows]


def test_fetch_range_creates_gap_report_when_unfilled(tmp_path):
    """A source that can't fill a > 1h old gap must leave a gap_reports row."""
    db = _fresh_db(tmp_path)
    # Align now so start/end are 60s-aligned and sit inside the MNQ session
    # window (avoid the 22:00-23:00 UTC daily break).
    now = 97_800
    end = now - 2 * 3600  # 90600, aligned
    start = end - 600  # 90000, aligned

    class _EmptySource:
        name = "empty"
        supported_timeframes = frozenset({"1m"})

        def fetch(self, *a, **kw):
            return []

    reg = _make_registry(_EmptySource(), clock=lambda: now)
    import services.ohlc.fetcher as fetcher_mod

    old = fetcher_mod._now
    fetcher_mod._now = lambda: now
    try:
        fetch_range(
            db_path=db,
            registry=reg,
            instrument="MNQ",
            timeframe="1m",
            start=start,
            end=end,
            trigger="maintainer",
        )
    finally:
        fetcher_mod._now = old

    conn = connect(db)
    rows = conn.execute("SELECT * FROM ohlc_gap_reports").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["state"] == "open"
    assert rows[0]["gap_start"] == start
    assert rows[0]["gap_end"] == end


def test_fetch_range_writes_attempt_even_when_cached(tmp_path):
    db = _fresh_db(tmp_path)
    conn = connect(db)
    for i in range(5):
        conn.execute(
            "INSERT INTO bars (instrument, timeframe, time, open, high, low,"
            " close, volume, source, fetched_at)"
            " VALUES ('MNQ', '1m', ?, 1, 1, 1, 1, 0, 'test', ?)",
            (i * 60, 0),
        )
    conn.close()

    reg = _make_registry(_GoodSource([]), clock=lambda: 10_000)
    result = fetch_range(
        db_path=db,
        registry=reg,
        instrument="MNQ",
        timeframe="1m",
        start=0,
        end=300,
        trigger="maintainer",
    )
    assert result.status == "cached"
    assert result.attempt_id != ""
    conn = connect(db)
    row = conn.execute(
        "SELECT final_status, bars_written FROM fetch_attempts WHERE id=?",
        (result.attempt_id,),
    ).fetchone()
    conn.close()
    assert row["final_status"] == "cached"
    assert row["bars_written"] == 0
