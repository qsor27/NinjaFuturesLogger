from pathlib import Path

from db import connect
from logging_config import get_logger
from models.bar import AttemptRecord, Bar, FetchResult
from services.ohlc.gap_detection import find_gaps
from services.ohlc.registry import SourceRegistry
from services.ohlc.store import insert_many

log = get_logger("ohlc.fetcher")


def fetch_range(
    *,
    db_path: Path | str,
    registry: SourceRegistry,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> FetchResult:
    """The single OHLC orchestration entry point.

    Steps:
      1. Find the missing sub-ranges in [start, end) the store doesn't have.
      2. For each missing sub-range, try each registry source in order.
         A source is skipped if its breaker is open OR if it doesn't
         declare the requested timeframe as supported.
      3. The first source that returns bars (even an empty list, treated as
         "this source had nothing for the range") fills the gap; we move on.
         A raised exception is recorded as a failure and we try the next
         source for the same gap.
      4. All collected bars are UPSERTed via the store in a single tick.
      5. Return a FetchResult with per-attempt forensics.

    The fetcher is the ONLY caller of source.fetch() in the entire app.
    Routes do not call it. Plan 14's post-tick hook submits it to the
    background pool; the scheduled refresh jobs call it on the scheduler
    thread.
    """
    if start >= end:
        return FetchResult(status="cached", bars_added=0, attempts=[])

    # Short-circuit if nothing in the registry supports this timeframe.
    if not any(timeframe in s.supported_timeframes for s, _b in registry.entries):
        return FetchResult(status="no_source_for_timeframe", bars_added=0, attempts=[])

    conn = connect(db_path)
    try:
        gaps = find_gaps(
            conn,
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
        )
        if not gaps:
            return FetchResult(status="cached", bars_added=0, attempts=[])
    finally:
        conn.close()

    bars_collected: list[Bar] = []
    attempts: list[AttemptRecord] = []
    any_gap_filled = False

    for gap_start, gap_end in gaps:
        gap_filled = False
        for source, breaker in list(registry.entries):
            if timeframe not in source.supported_timeframes:
                continue
            if not breaker.allows():
                attempts.append(AttemptRecord(
                    source=source.name, outcome="skipped", count=0, error=None,
                ))
                continue
            try:
                bars = source.fetch(instrument, timeframe, gap_start, gap_end)
                breaker.record_success()
                bars_collected.extend(bars)
                attempts.append(AttemptRecord(
                    source=source.name, outcome="ok", count=len(bars), error=None,
                ))
                gap_filled = True
                break
            except Exception as e:
                breaker.record_failure(e)
                attempts.append(AttemptRecord(
                    source=source.name, outcome="failed", count=0, error=repr(e),
                ))
                continue
        if gap_filled:
            any_gap_filled = True

    if bars_collected:
        conn = connect(db_path)
        try:
            conn.execute("BEGIN")
            try:
                insert_many(conn, bars_collected)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    if bars_collected:
        status = "ok" if any_gap_filled else "partial"
    elif any_gap_filled:
        status = "ok"
    else:
        status = "all_sources_unavailable"

    log.info(
        "fetch_range done",
        extra={
            "instrument": instrument,
            "tf": timeframe,
            "bars_added": len(bars_collected),
            "status": status,
        },
    )
    return FetchResult(
        status=status,
        bars_added=len(bars_collected),
        attempts=attempts,
    )
