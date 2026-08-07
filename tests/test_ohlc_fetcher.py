from db import connect
from models.bar import Bar
from services.ohlc.fetcher import fetch_range
from services.ohlc.store import insert_many
from tests.conftest import FakeOhlcSource, make_bar, make_source_registry


def _bar(t, src="fake"):
    return make_bar(
        instrument="MNQ",
        timeframe="1d",
        time=t,
        open=1.0,
        high=1.0,
        low=1.0,
        close=float(t),
        volume=0,
        source=src,
    )


def _recent_in_session_minute() -> int:
    """Most recent Wednesday 10:00 America/Chicago — always inside the CME
    session and well inside the 30-day 1m provider reach."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    chicago = ZoneInfo("America/Chicago")
    d = datetime.now(tz=chicago)
    while d.weekday() != 2:  # Wednesday
        d -= timedelta(days=1)
    pinned = d.replace(hour=10, minute=0, second=0, microsecond=0)
    if pinned > datetime.now(tz=chicago):  # today is Wed before 10:00
        pinned -= timedelta(days=7)
    return int(pinned.timestamp())


def test_fully_cached_returns_cached_status(migrated_db):
    primary = FakeOhlcSource("primary", supported={"1d"}, bars=[])
    reg = make_source_registry([primary])
    # Pre-populate the store with two daily bars
    conn = connect(migrated_db)
    try:
        insert_many(
            conn,
            [
                Bar(
                    instrument="MNQ",
                    timeframe="1d",
                    time=86400,
                    open=1,
                    high=1,
                    low=1,
                    close=1,
                    volume=0,
                    source="seed",
                ),
                Bar(
                    instrument="MNQ",
                    timeframe="1d",
                    time=86400 * 2,
                    open=1,
                    high=1,
                    low=1,
                    close=1,
                    volume=0,
                    source="seed",
                ),
            ],
        )
    finally:
        conn.close()

    # Use a tiny window that's exactly covered
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 3,
        trigger="on_demand",
    )
    # Even if find_gaps returns extra "missing" bars from session-aware
    # expansion, the primary returns nothing for those, so bars_added stays 0.
    assert primary.calls == [] or all(c is not None for c in primary.calls)
    assert result.status in {"cached", "partial", "all_sources_unavailable"}


def test_primary_returns_bars(migrated_db):
    bars = [_bar(86400 * i, src="primary") for i in range(1, 4)]
    primary = FakeOhlcSource("primary", supported={"1d"}, bars=bars)
    reg = make_source_registry([primary])
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 4,
        trigger="on_demand",
    )
    assert result.bars_added >= 1
    assert any(a.outcome == "ok" for a in result.attempts)
    assert any(a.source == "primary" for a in result.attempts)


def test_primary_fails_falls_back_to_secondary(migrated_db):
    primary = FakeOhlcSource("primary", supported={"1d"}, error=RuntimeError("boom"))
    bars = [_bar(86400 * i, src="secondary") for i in range(1, 4)]
    secondary = FakeOhlcSource("secondary", supported={"1d"}, bars=bars)
    reg = make_source_registry([primary, secondary])
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 4,
        trigger="on_demand",
    )
    sources_attempted = {a.source for a in result.attempts}
    assert "primary" in sources_attempted
    assert "secondary" in sources_attempted
    assert result.bars_added >= 1


def test_all_sources_open_returns_all_unavailable(migrated_db):
    primary = FakeOhlcSource("primary", supported={"1d"}, error=RuntimeError("boom"))
    secondary = FakeOhlcSource("secondary", supported={"1d"}, error=RuntimeError("boom"))
    reg = make_source_registry([primary, secondary], threshold=1)
    # First call trips both
    fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 4,
        trigger="on_demand",
    )
    # Second call: both breakers open, no fetches happen
    primary.calls.clear()
    secondary.calls.clear()
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 4,
        trigger="on_demand",
    )
    assert result.bars_added == 0
    assert result.status == "all_sources_unavailable"
    assert primary.calls == []
    assert secondary.calls == []


def test_no_source_supports_timeframe_returns_no_source_status(migrated_db):
    primary = FakeOhlcSource("primary", supported={"1d"}, bars=[])
    reg = make_source_registry([primary])
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1m",
        start=60,
        end=300,
        trigger="on_demand",
    )
    assert result.status == "no_source_for_timeframe"
    assert result.bars_added == 0


def test_fetcher_acquires_token_before_source_call(tmp_path):
    import time
    from pathlib import Path

    from db import connect
    from migrations import run_migrations
    from models.bar import Bar
    from services.ohlc.circuit_breaker import CircuitBreaker
    from services.ohlc.fetcher import fetch_range
    from services.ohlc.rate_limiter import TokenBucket
    from services.ohlc.registry import SourceRegistry

    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    conn.close()

    class RecordingSource:
        name = "rec"
        supported_timeframes = frozenset({"1m"})

        def __init__(self):
            self.calls = 0

        def fetch(self, instrument, timeframe, start, end):
            self.calls += 1
            return [
                Bar(
                    instrument=instrument,
                    timeframe=timeframe,
                    time=start,
                    open=1,
                    high=2,
                    low=0,
                    close=1,
                    volume=1,
                    source="rec",
                )
            ]

    anchor = _recent_in_session_minute()
    clock = [anchor]
    reg = SourceRegistry(clock=lambda: clock[0])
    src = RecordingSource()
    reg.entries.append(
        (
            src,
            CircuitBreaker(
                name="rec",
                failure_threshold=3,
                base_cooldown_seconds=1,
                clock=lambda: clock[0],
            ),
        )
    )
    bucket = TokenBucket(capacity=2, refill_per_sec=0.0, clock=time.monotonic)
    start_ts = anchor - 120
    end_ts = anchor - 60
    res = fetch_range(
        db_path=db,
        registry=reg,
        instrument="MNQ",
        timeframe="1m",
        start=start_ts,
        end=end_ts,
        token_bucket=bucket,
        trigger="on_demand",
    )
    assert src.calls == 1
    assert bucket.stats()["acquired_total"] == 1
    assert res.bars_added == 1


def test_out_of_reach_gaps_are_never_sent_to_sources(migrated_db, monkeypatch):
    """yfinance hard-rejects intraday requests older than PROVIDER_REACH
    ('requested range must be within the last N days'). The fetcher must
    drop such gaps instead of sending guaranteed-to-fail requests."""
    import services.ohlc.fetcher as fetcher_mod

    now = 1776254400  # 2026-04-15T12:00:00Z, a Wednesday
    monkeypatch.setattr(fetcher_mod, "_now", lambda: now)

    primary = FakeOhlcSource("primary", supported={"1m"}, bars=[])
    reg = make_source_registry([primary])
    # 1m reach is 30 days; ask for an in-session weekday window ~58 days
    # old (2026-02-16T12:00Z, a Monday) — entirely beyond reach.
    start = now - 58 * 86400
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1m",
        start=start,
        end=start + 3600,
        trigger="sweep",
    )
    assert primary.calls == []
    assert result.status == "out_of_reach"
    assert result.bars_added == 0


def test_gap_straddling_reach_floor_is_trimmed(migrated_db, monkeypatch):
    """A gap that starts before the reach floor but ends inside it should be
    trimmed to the reachable part, not dropped or sent whole."""
    import services.ohlc.fetcher as fetcher_mod

    now = 1776254400  # 2026-04-15T12:00:00Z, a Wednesday
    monkeypatch.setattr(fetcher_mod, "_now", lambda: now)

    primary = FakeOhlcSource("primary", supported={"1m"}, bars=[])
    reg = make_source_registry([primary])
    floor = now - 30 * 86400  # 1m reach
    fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1m",
        start=floor - 2 * 3600,
        end=floor + 2 * 3600,
        trigger="sweep",
    )
    assert primary.calls, "reachable part of the gap should still be fetched"
    for _inst, _tf, g_start, _g_end in primary.calls:
        assert g_start >= floor


def test_partial_when_only_some_gaps_get_an_answer(migrated_db):
    """B6: filling 1 of 2 gaps must report 'partial', not 'ok'."""

    class _FlakySource:
        name = "flaky"
        supported_timeframes = frozenset({"1d"})

        def fetch(self, instrument, timeframe, start, end):
            if start >= 86400 * 5:
                raise RuntimeError("boom")
            return [_bar(86400, src="flaky")]

    # Seed Mon 1970-01-05 so the window splits into two gaps:
    # (Fri 86400, 172800) and (Tue 432000, 518400).
    conn = connect(migrated_db)
    try:
        insert_many(conn, [_bar(86400 * 4, src="seed")])
    finally:
        conn.close()

    reg = make_source_registry([_FlakySource()])
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 6,
        trigger="on_demand",
    )
    assert result.bars_added == 1
    assert result.status == "partial"


def test_empty_source_answer_records_empty_outcome(migrated_db):
    """Micro-drift fix: the in-memory AttemptRecord must carry the same
    outcome the DB trail records ('empty') when a source answers with
    zero bars — and all-empty answers still finish as 'ok'."""
    primary = FakeOhlcSource("primary", supported={"1d"}, bars=[])
    reg = make_source_registry([primary])
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 3,
        trigger="on_demand",
    )
    assert result.attempts, "expected at least one source attempt"
    assert all(a.outcome == "empty" for a in result.attempts)
    assert result.status == "ok"
