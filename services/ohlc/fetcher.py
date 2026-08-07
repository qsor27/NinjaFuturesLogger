import time
from pathlib import Path

from db import read_conn, transaction
from logging_config import get_logger
from models.bar import AttemptRecord, Bar, FetchResult, FetchStatus, Outcome
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


class _AttemptTrail:
    """Forensic trail for one fetch_range call: writes the per-source DB
    row, emits the structured log line, and accumulates the in-memory
    AttemptRecord list that FetchResult returns."""

    def __init__(
        self,
        *,
        db_path: Path | str,
        attempt_id: str,
        trigger: str,
        instrument: str,
        timeframe: str,
    ) -> None:
        self._db_path = db_path
        self._attempt_id = attempt_id
        self._trigger = trigger
        self._instrument = instrument
        self._timeframe = timeframe
        self.records: list[AttemptRecord] = []

    def record(
        self,
        *,
        source_name: str,
        g_start: int,
        g_end: int,
        outcome: str,
        bars_returned: int = 0,
        duration_ms: int | None = None,
        http_status_code: int | None = None,
        error_class: str | None = None,
        error: str | None = None,
        attempt_outcome: Outcome | None = None,
    ) -> None:
        """DB trail row + log line; when attempt_outcome is given, also an
        in-memory AttemptRecord (vocabularies differ: the DB stores e.g.
        'skipped_breaker', FetchResult stores 'skipped'). AttemptRecord's
        count always equals bars_returned (0 for skipped/failed)."""
        _record_source(
            self._db_path,
            self._attempt_id,
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
                "attempt_id": self._attempt_id,
                "trigger": self._trigger,
                "instrument": self._instrument,
                "tf": self._timeframe,
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
        if attempt_outcome is not None:
            self.records.append(
                AttemptRecord(
                    source=source_name,
                    outcome=attempt_outcome,
                    count=bars_returned,
                    error=error,
                )
            )


def _try_sources_for_gap(
    *,
    registry: SourceRegistry,
    db_path: Path | str,
    instrument: str,
    timeframe: str,
    gap_start: int,
    gap_end: int,
    token_bucket: TokenBucket | None,
    trail: _AttemptTrail,
) -> tuple[list[Bar], bool]:
    """Try each registered source in order for one gap.

    Module-private and called only by fetch_range — the load-bearing rule
    "fetch_range is the only function that calls a source" holds at the
    module boundary; no other entry point reaches source.fetch.

    Returns (bars, gap_filled): bars is the first answering source's
    result (possibly empty), gap_filled is True iff some source answered
    without raising. ([], False) when every source was skipped or failed.
    """
    for source, breaker in list(registry.entries):
        if timeframe not in source.supported_timeframes:
            trail.record(
                source_name=source.name,
                g_start=gap_start,
                g_end=gap_end,
                outcome="skipped_no_timeframe",
            )
            continue
        if not breaker.allows():
            trail.record(
                source_name=source.name,
                g_start=gap_start,
                g_end=gap_end,
                outcome="skipped_breaker",
                attempt_outcome="skipped",
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
            trail.record(
                source_name=source.name,
                g_start=gap_start,
                g_end=gap_end,
                outcome="skipped_rate_limit",
                duration_ms=dur_ms,
                error_class="rate_limit_token_bucket",
                error=repr(te),
                attempt_outcome="skipped",
            )
            continue
        except Exception as e:
            dur_ms = int((time.monotonic() - t0) * 1000)
            breaker.record_failure(e)
            _persist_breaker(db_path, breaker)
            trail.record(
                source_name=source.name,
                g_start=gap_start,
                g_end=gap_end,
                outcome="failed",
                duration_ms=dur_ms,
                http_status_code=http_status(e),
                error_class=classify_exception(e)[0],
                error=repr(e),
                attempt_outcome="failed",
            )
            continue

        dur_ms = int((time.monotonic() - t0) * 1000)
        breaker.record_success()
        _persist_breaker(db_path, breaker)
        outcome = "ok" if bars else "empty"
        trail.record(
            source_name=source.name,
            g_start=gap_start,
            g_end=gap_end,
            outcome=outcome,
            bars_returned=len(bars),
            duration_ms=dur_ms,
            attempt_outcome=outcome,
        )
        return bars, True
    return [], False


def _short_circuit(
    *,
    db_path: Path | str,
    attempt_id: str,
    status: FetchStatus,
    gaps_found: int,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> FetchResult:
    """Finalize an attempt that never reached a source; build its result."""
    _finalize(db_path, attempt_id, gaps_found, 0, status, None, instrument, timeframe, start, end)
    return FetchResult(status=status, bars_added=0, attempts=[], attempt_id=attempt_id)


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

    if start >= end:
        return _short_circuit(
            db_path=db_path,
            attempt_id=attempt_id,
            status="cached",
            gaps_found=0,
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
        )

    if not any(timeframe in s.supported_timeframes for s, _b in registry.entries):
        return _short_circuit(
            db_path=db_path,
            attempt_id=attempt_id,
            status="no_source_for_timeframe",
            gaps_found=0,
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
        )

    with read_conn(db_path) as conn:
        gaps = find_gaps(conn, instrument=instrument, timeframe=timeframe, start=start, end=end)

    if not gaps:
        return _short_circuit(
            db_path=db_path,
            attempt_id=attempt_id,
            status="cached",
            gaps_found=0,
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
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
        return _short_circuit(
            db_path=db_path,
            attempt_id=attempt_id,
            status="out_of_reach",
            gaps_found=dropped_out_of_reach,
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
        )

    trail = _AttemptTrail(
        db_path=db_path,
        attempt_id=attempt_id,
        trigger=trigger,
        instrument=instrument,
        timeframe=timeframe,
    )
    bars_collected: list[Bar] = []
    any_gap_filled = False
    all_gaps_filled = True
    for gap_start, gap_end in gaps:
        bars, gap_filled = _try_sources_for_gap(
            registry=registry,
            db_path=db_path,
            instrument=instrument,
            timeframe=timeframe,
            gap_start=gap_start,
            gap_end=gap_end,
            token_bucket=token_bucket,
            trail=trail,
        )
        bars_collected.extend(bars)
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
        attempts=trail.records,
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
