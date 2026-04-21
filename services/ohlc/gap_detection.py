import sqlite3
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from services.instruments import default_session, is_full_closure
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


def expected_session_slots(
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> list[int]:
    """Generate the timeframe-aligned slots in [start, end) that fall inside
    the instrument's trading session (i.e. NOT during the daily break).
    Public since 2026-04-21 so services/mfe_mae.py can compute coverage."""
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

    # Daily+ bars from futures providers are only emitted for trade dates
    # (Mon–Fri). Without this, every Saturday/Sunday slot shows up as a
    # perpetual missing gap that no fetch can ever fill.
    skip_weekends = stride >= 86400

    slots: list[int] = []
    t = aligned_start
    while t < end:
        if skip_weekends:
            weekday = datetime.fromtimestamp(t, tz=UTC).weekday()
            if weekday >= 5:
                t += stride
                continue
            if is_full_closure(instrument, t):
                t += stride
                continue
        if not has_break or not _is_in_break(t, tz, bs, be):
            slots.append(t)
        t += stride
    return slots


def expected_slot_count(
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> int:
    """Number of session-aware slots in [start, end). Wrapper around
    expected_session_slots for callers that only need the count."""
    return len(expected_session_slots(instrument, timeframe, start, end))


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
    expected = expected_session_slots(instrument, timeframe, start, end)
    if not expected:
        return []
    present_times = list_times(
        conn, instrument=instrument, timeframe=timeframe, start=start, end=end
    )

    stride = timeframe_seconds(timeframe)
    if stride >= 86400:
        # Daily and above: yfinance stamps daily futures bars at local
        # midnight (04:00/05:00 UTC), but expected_session_slots walks epoch-
        # aligned 00:00 UTC slots. Exact equality never matches, so bucket
        # both sides to the UTC calendar day — "did we get a bar for this
        # day?" is all that matters at these timeframes.
        present_buckets = {t // 86400 for t in present_times}
        is_present = lambda slot: (slot // 86400) in present_buckets  # noqa: E731
    else:
        present = set(present_times)
        is_present = lambda slot: slot in present  # noqa: E731

    gaps: list[tuple[int, int]] = []
    run_start: int | None = None
    prev_slot: int | None = None
    for slot in expected:
        if is_present(slot):
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
    slots = expected_session_slots(instrument, timeframe, start, end)
    reach = PROVIDER_REACH.get(timeframe, PROVIDER_REACH["1d"])
    reach_cutoff = now - reach
    reachable = [s for s in slots if s >= reach_cutoff]
    out_of_reach = len(slots) - len(reachable)
    present_times = list_times(
        conn, instrument=instrument, timeframe=timeframe, start=start, end=end
    )
    # For daily-and-above, the walker anchors at the session open (e.g. 17:00 CT)
    # but providers like yfinance stamp daily bars at 00:00 UTC — so exact-time
    # matching never aligns. Bucket both sides to a UTC calendar day instead;
    # the only thing that matters at these timeframes is "did we get a bar for
    # this day?".
    if timeframe_seconds(timeframe) >= 86400:
        present_days = {t // 86400 for t in present_times}
        present_count = sum(1 for s in reachable if (s // 86400) in present_days)
    else:
        present = set(present_times)
        present_count = sum(1 for s in reachable if s in present)
    missing = len(reachable) - present_count
    return {
        "expected": len(slots),
        "present": present_count,
        "missing": missing,
        "out_of_reach": out_of_reach,
    }
