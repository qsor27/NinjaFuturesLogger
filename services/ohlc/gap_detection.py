import sqlite3
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from services.instruments import default_session
from services.ohlc.reach import PROVIDER_REACH
from services.ohlc.store import list_times

_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "1wk": 7 * 86400,
    "1mo": 30 * 86400,
}


def timeframe_seconds(timeframe: str) -> int:
    try:
        return _TIMEFRAME_SECONDS[timeframe]
    except KeyError as e:
        raise ValueError(f"unknown timeframe: {timeframe}") from e


def _hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def _is_in_break(ts: int, tz: ZoneInfo, break_start: time, break_end: time) -> bool:
    """Is this UTC unix timestamp inside the instrument's daily break?"""
    local = datetime.fromtimestamp(ts, tz=UTC).astimezone(tz).time()
    if break_start <= break_end:
        return break_start <= local < break_end
    # break wraps midnight
    return local >= break_start or local < break_end


def _expected_slots(
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> list[int]:
    """Generate the timeframe-aligned slots in [start, end) that fall inside
    the instrument's trading session (i.e. NOT during the daily break)."""
    stride = timeframe_seconds(timeframe)
    aligned_start = start - (start % stride)
    if aligned_start < start:
        aligned_start += stride

    session = default_session(instrument)
    tz = ZoneInfo(session.timezone)
    has_break = bool(session.daily_break_start) and bool(session.daily_break_end)
    if has_break:
        bs = _hhmm(session.daily_break_start)
        be = _hhmm(session.daily_break_end)

    slots: list[int] = []
    t = aligned_start
    while t < end:
        if not has_break or not _is_in_break(t, tz, bs, be):
            slots.append(t)
        t += stride
    return slots


def find_gaps(
    conn: sqlite3.Connection,
    *,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    """Minimal ``(sub_start, sub_end)`` ranges in [start, end) the store is missing.

    Consults the instrument's session calendar (currently a stub default;
    plan 16 makes it per-instrument) so the daily break is not flagged as
    missing.
    """
    if start >= end:
        return []
    expected = _expected_slots(instrument, timeframe, start, end)
    if not expected:
        return []
    present = set(
        list_times(conn, instrument=instrument, timeframe=timeframe, start=start, end=end)
    )

    stride = timeframe_seconds(timeframe)
    gaps: list[tuple[int, int]] = []
    run_start: int | None = None
    prev_slot: int | None = None
    for slot in expected:
        if slot in present:
            if run_start is not None:
                gaps.append((run_start, prev_slot + stride))  # type: ignore[operator]
                run_start = None
            prev_slot = slot
            continue
        if run_start is None:
            run_start = slot
        prev_slot = slot
    if run_start is not None:
        gaps.append((run_start, prev_slot + stride))  # type: ignore[operator]
    return gaps


def classify_window(
    conn: sqlite3.Connection,
    *,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
    now: int,
) -> dict:
    """Summarize a window as {expected, present, missing, out_of_reach}.

    A slot is `out_of_reach` if the provider cannot serve it even on a
    fresh fetch (yfinance 1m -> only last 7 days). Everything beyond the
    reach threshold is classified as out_of_reach, not missing.
    """
    if start >= end:
        return {"expected": 0, "present": 0, "missing": 0, "out_of_reach": 0}
    slots = _expected_slots(instrument, timeframe, start, end)
    reach = PROVIDER_REACH.get(timeframe, PROVIDER_REACH["1d"])
    reach_cutoff = now - reach
    reachable = [s for s in slots if s >= reach_cutoff]
    out_of_reach = len(slots) - len(reachable)
    present = set(
        list_times(conn, instrument=instrument, timeframe=timeframe, start=start, end=end)
    )
    present_count = sum(1 for s in reachable if s in present)
    missing = len(reachable) - present_count
    return {
        "expected": len(slots),
        "present": present_count,
        "missing": missing,
        "out_of_reach": out_of_reach,
    }
