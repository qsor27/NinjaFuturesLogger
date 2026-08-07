import time
from pathlib import Path

from db import read_conn, transaction
from logging_config import get_logger
from models.bar import AttemptRecord, Bar, FetchResult
from services.ohlc._classify import classify_exception, http_status
from services.ohlc.attempts import (
    begin_attempt,
    complete_attempt,
    new_attempt_id,
    record_source_attempt,
)
from services.ohlc.breaker_persistence import persist_breaker
from services.ohlc.circuit_breaker import CircuitBreaker
from services.ohlc.gap_detection import find_gaps
from services.ohlc.gap_reports import update_gap_reports
from services.ohlc.rate_limiter import TokenBucket
from services.ohlc.reach import REACH_MARGIN_SECONDS, reach_floor
from services.ohlc.registry import SourceRegistry
from services.ohlc.store import insert_many

log = get_logger("ohlc.fetcher")


def _clamp_gaps_to_reach(
    gaps: list[tuple[int, int]], *, timeframe: str, now: int
) -> tuple[list[tuple[int, int]], int]:
    """Drop or trim gaps the provider can no longer serve.

    Delegates the floor formula to reach.reach_floor (None = unlimited,
    never clamped). Returns (clamped_gaps, dropped_count).
    """
    floor = reach_floor(timeframe, now=now, margin=REACH_MARGIN_SECONDS)
    if floor is None:
        return gaps, 0
    clamped: list[tuple[int, int]] = []
    dropped = 0
    for g_start, g_end in gaps:
        if g_end <= floor:
            dropped += 1
            continue
        clamped.append((max(g_start, floor), g_end))
    return clamped, dropped


# Indirection so tests can monkeypatch the "now" clock the gap-report writer
# reads. Production code uses wall-clock seconds.
def _now() -> int:
    return int(time.time())


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
    'on_demand', 'self_heal'. Any string is stored verbatim;
    the dashboard filters and groups by it.
    """
    attempt_id = new_attempt_id()
    now = _now()

    with transaction(db_path) as conn:
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

    with read_conn(db_path) as conn:
        gaps = find_gaps(
            conn,
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
        )

    if not gaps:
        _finalize(db_path, attempt_id, 0, 0, "cached", None, instrument, timeframe, start, end)
        return FetchResult(
            status="cached",
            bars_added=0,
            attempts=[],
            attempt_id=attempt_id,
        )

    gaps, dropped_out_of_reach = _clamp_gaps_to_reach(gaps, timeframe=timeframe, now=now)
    if dropped_out_of_reach:
        log.info(
            "dropped out-of-reach gaps",
            extra={
                "attempt_id": attempt_id,
                "instrument": instrument,
                "tf": timeframe,
                "dropped": dropped_out_of_reach,
            },
        )
    if not gaps:
        _finalize(
            db_path,
            attempt_id,
            dropped_out_of_reach,
            0,
            "out_of_reach",
            None,
            instrument,
            timeframe,
            start,
            end,
        )
        return FetchResult(
            status="out_of_reach",
            bars_added=0,
            attempts=[],
            attempt_id=attempt_id,
        )

    bars_collected: list[Bar] = []
    attempts: list[AttemptRecord] = []
    any_gap_filled = False
    all_gaps_filled = True

    def _record_and_log(
        *,
        source_name: str,
        g_start: int,
        g_end: int,
        outcome: str,
        bars_returned: int,
        duration_ms: int | None,
        http_status_code: int | None,
        error_class: str | None,
        error: str | None,
    ) -> None:
        _record_source(
            db_path,
            attempt_id,
            g_start,
            g_end,
            source_name,
            outcome,
            bars_returned,
            duration_ms,
            http_status_code,
            error_class,
            error,
        )
        log.info(
            "ohlc source attempt",
            extra={
                "attempt_id": attempt_id,
                "trigger": trigger,
                "instrument": instrument,
                "tf": timeframe,
                "gap_start": g_start,
                "gap_end": g_end,
                "source": source_name,
                "outcome": outcome,
                "bars_returned": bars_returned,
                "duration_ms": duration_ms,
                "error_class": error_class,
                "error": error,
            },
        )

    for gap_start, gap_end in gaps:
        gap_filled = False
        for source, breaker in list(registry.entries):
            if timeframe not in source.supported_timeframes:
                _record_and_log(
                    source_name=source.name,
                    g_start=gap_start,
                    g_end=gap_end,
                    outcome="skipped_no_timeframe",
                    bars_returned=0,
                    duration_ms=None,
                    http_status_code=None,
                    error_class=None,
                    error=None,
                )
                continue
            if not breaker.allows():
                _record_and_log(
                    source_name=source.name,
                    g_start=gap_start,
                    g_end=gap_end,
                    outcome="skipped_breaker",
                    bars_returned=0,
                    duration_ms=None,
                    http_status_code=None,
                    error_class=None,
                    error=None,
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
                _record_and_log(
                    source_name=source.name,
                    g_start=gap_start,
                    g_end=gap_end,
                    outcome="skipped_rate_limit",
                    bars_returned=0,
                    duration_ms=dur_ms,
                    http_status_code=None,
                    error_class="rate_limit_token_bucket",
                    error=repr(te),
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
                _record_and_log(
                    source_name=source.name,
                    g_start=gap_start,
                    g_end=gap_end,
                    outcome="failed",
                    bars_returned=0,
                    duration_ms=dur_ms,
                    http_status_code=http_status(e),
                    error_class=classify_exception(e)[0],
                    error=repr(e),
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
            _record_and_log(
                source_name=source.name,
                g_start=gap_start,
                g_end=gap_end,
                outcome=outcome,
                bars_returned=len(bars),
                duration_ms=dur_ms,
                http_status_code=None,
                error_class=None,
                error=None,
            )
            attempts.append(
                AttemptRecord(
                    source=source.name,
                    outcome=outcome,
                    count=len(bars),
                    error=None,
                )
            )
            gap_filled = True
            break
        if gap_filled:
            any_gap_filled = True
        else:
            all_gaps_filled = False

    if bars_collected:
        with transaction(db_path) as conn:
            insert_many(conn, bars_collected)

    if not any_gap_filled:
        status = "all_sources_unavailable"
    elif all_gaps_filled:
        status = "ok"
    else:
        status = "partial"

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
        with transaction(db_path) as conn:
            persist_breaker(conn, breaker, now=_now())
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
    http_status_code,
    error_class,
    error,
):
    with transaction(db_path) as conn:
        record_source_attempt(
            conn,
            attempt_id=attempt_id,
            gap_start=gap_start,
            gap_end=gap_end,
            source=source,
            outcome=outcome,
            bars_returned=bars_returned,
            duration_ms=duration_ms,
            http_status=http_status_code,
            error_class=error_class,
            error=error,
        )


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
    with transaction(db_path) as conn:
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
