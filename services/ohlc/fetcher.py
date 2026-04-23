import time
from pathlib import Path

from db import connect
from logging_config import get_logger
from models.bar import AttemptRecord, Bar, FetchResult
from services.ohlc.attempts import (
    begin_attempt,
    complete_attempt,
    new_attempt_id,
    record_source_attempt,
)
from services.ohlc.breaker_persistence import persist_breaker
from services.ohlc.circuit_breaker import CircuitBreaker, FailureClassification
from services.ohlc.gap_detection import find_gaps
from services.ohlc.gap_reports import update_gap_reports
from services.ohlc.rate_limiter import TokenBucket
from services.ohlc.registry import SourceRegistry
from services.ohlc.store import insert_many

log = get_logger("ohlc.fetcher")


# Indirection so tests can monkeypatch the "now" clock the gap-report writer
# reads. Production code uses wall-clock seconds.
def _now() -> int:
    return int(time.time())


def _error_class(err: BaseException) -> str | None:
    attached = getattr(err, "ftl_failure", None)
    if isinstance(attached, FailureClassification):
        return attached.failure_class
    response = getattr(err, "response", None)
    code = getattr(response, "status_code", None)
    if code == 429:
        return "rate_limit"
    if code is not None and 500 <= code < 600:
        return "server_error"
    return None


def _http_status(err: BaseException) -> int | None:
    response = getattr(err, "response", None)
    code = getattr(response, "status_code", None)
    return int(code) if code is not None else None


def fetch_range(
    *,
    db_path: Path | str,
    registry: SourceRegistry,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
    trigger: str,
    token_bucket: TokenBucket | None = None,
) -> FetchResult:
    """Orchestrate a fetch and persist a full forensic trail.

    `trigger` is required. Accepted values include 'maintainer', 'sweep',
    'on_demand', 'self_heal', 'post_import'. Any string is stored verbatim;
    the dashboard filters and groups by it.
    """
    attempt_id = new_attempt_id()
    now = _now()

    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        begin_attempt(
            conn,
            attempt_id=attempt_id,
            trigger=trigger,
            instrument=instrument,
            timeframe=timeframe,
            range_start=start,
            range_end=end,
            now=now,
        )
        conn.execute("COMMIT")
    finally:
        conn.close()

    # Short-circuit: empty range.
    if start >= end:
        _finalize(db_path, attempt_id, 0, 0, "cached", None, instrument, timeframe, start, end)
        return FetchResult(
            status="cached",
            bars_added=0,
            attempts=[],
            attempt_id=attempt_id,
        )

    # Short-circuit: no source supports this timeframe.
    if not any(timeframe in s.supported_timeframes for s, _b in registry.entries):
        _finalize(
            db_path,
            attempt_id,
            0,
            0,
            "no_source_for_timeframe",
            None,
            instrument,
            timeframe,
            start,
            end,
        )
        return FetchResult(
            status="no_source_for_timeframe",
            bars_added=0,
            attempts=[],
            attempt_id=attempt_id,
        )

    conn = connect(db_path)
    try:
        gaps = find_gaps(
            conn,
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
        )
    finally:
        conn.close()

    if not gaps:
        _finalize(db_path, attempt_id, 0, 0, "cached", None, instrument, timeframe, start, end)
        return FetchResult(
            status="cached",
            bars_added=0,
            attempts=[],
            attempt_id=attempt_id,
        )

    bars_collected: list[Bar] = []
    attempts: list[AttemptRecord] = []
    any_gap_filled = False

    for gap_start, gap_end in gaps:
        gap_filled = False
        for source, breaker in list(registry.entries):
            if timeframe not in source.supported_timeframes:
                _record_source(
                    db_path,
                    attempt_id,
                    gap_start,
                    gap_end,
                    source.name,
                    "skipped_no_timeframe",
                    0,
                    None,
                    None,
                    None,
                    None,
                )
                continue
            if not breaker.allows():
                _record_source(
                    db_path,
                    attempt_id,
                    gap_start,
                    gap_end,
                    source.name,
                    "skipped_breaker",
                    0,
                    None,
                    None,
                    None,
                    None,
                )
                attempts.append(
                    AttemptRecord(
                        source=source.name,
                        outcome="skipped",
                        count=0,
                        error=None,
                    )
                )
                continue

            t0 = time.monotonic()
            try:
                if token_bucket is not None:
                    with token_bucket.acquire(timeout=60):
                        bars = source.fetch(instrument, timeframe, gap_start, gap_end)
                else:
                    bars = source.fetch(instrument, timeframe, gap_start, gap_end)
            except TimeoutError as te:
                dur_ms = int((time.monotonic() - t0) * 1000)
                _record_source(
                    db_path,
                    attempt_id,
                    gap_start,
                    gap_end,
                    source.name,
                    "skipped_rate_limit",
                    0,
                    dur_ms,
                    None,
                    "rate_limit_token_bucket",
                    repr(te),
                )
                attempts.append(
                    AttemptRecord(
                        source=source.name,
                        outcome="skipped",
                        count=0,
                        error=repr(te),
                    )
                )
                continue
            except Exception as e:
                dur_ms = int((time.monotonic() - t0) * 1000)
                breaker.record_failure(e)
                _persist_breaker(db_path, breaker)
                _record_source(
                    db_path,
                    attempt_id,
                    gap_start,
                    gap_end,
                    source.name,
                    "failed",
                    0,
                    dur_ms,
                    _http_status(e),
                    _error_class(e),
                    repr(e),
                )
                attempts.append(
                    AttemptRecord(
                        source=source.name,
                        outcome="failed",
                        count=0,
                        error=repr(e),
                    )
                )
                continue

            dur_ms = int((time.monotonic() - t0) * 1000)
            breaker.record_success()
            _persist_breaker(db_path, breaker)
            bars_collected.extend(bars)
            outcome = "ok" if bars else "empty"
            _record_source(
                db_path,
                attempt_id,
                gap_start,
                gap_end,
                source.name,
                outcome,
                len(bars),
                dur_ms,
                None,
                None,
                None,
            )
            attempts.append(
                AttemptRecord(
                    source=source.name,
                    outcome="ok",
                    count=len(bars),
                    error=None,
                )
            )
            gap_filled = True
            break
        if gap_filled:
            any_gap_filled = True

    if bars_collected:
        conn = connect(db_path)
        try:
            conn.execute("BEGIN")
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

    _finalize(
        db_path,
        attempt_id,
        len(gaps),
        len(bars_collected),
        status,
        None,
        instrument,
        timeframe,
        start,
        end,
    )

    log.info(
        "fetch_range done",
        extra={
            "attempt_id": attempt_id,
            "trigger": trigger,
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
        attempt_id=attempt_id,
    )


def _persist_breaker(db_path, breaker: CircuitBreaker) -> None:
    """Best-effort persistence of breaker state. Errors are non-fatal."""
    try:
        conn = connect(db_path)
        try:
            conn.execute("BEGIN")
            persist_breaker(conn, breaker, now=_now())
            conn.execute("COMMIT")
        finally:
            conn.close()
    except Exception:
        log.exception("breaker persist failed", extra={"source": breaker.name})


def _record_source(
    db_path,
    attempt_id,
    gap_start,
    gap_end,
    source,
    outcome,
    bars_returned,
    duration_ms,
    http_status,
    error_class,
    error,
):
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        record_source_attempt(
            conn,
            attempt_id=attempt_id,
            gap_start=gap_start,
            gap_end=gap_end,
            source=source,
            outcome=outcome,
            bars_returned=bars_returned,
            duration_ms=duration_ms,
            http_status=http_status,
            error_class=error_class,
            error=error,
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


def _finalize(
    db_path,
    attempt_id,
    gaps_found,
    bars_written,
    final_status,
    error,
    instrument,
    timeframe,
    start,
    end,
):
    now = _now()
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        complete_attempt(
            conn,
            attempt_id=attempt_id,
            now=now,
            gaps_found=gaps_found,
            bars_written=bars_written,
            final_status=final_status,
            error=error,
        )
        update_gap_reports(
            conn,
            instrument=instrument,
            timeframe=timeframe,
            range_start=start,
            range_end=end,
            attempt_id=attempt_id,
            now=now,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
