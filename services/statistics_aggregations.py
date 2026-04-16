"""Pure aggregation helpers for plan 15 statistics.

Every function here is referentially transparent: takes data, returns data,
no I/O, no globals, no clock. Each helper is unit-tested in isolation in
tests/test_statistics_aggregations.py. The StatisticsService is only a
thin I/O wrapper that calls these.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Literal
from zoneinfo import ZoneInfo

from models.position import Position
from models.statistics import (
    DayOfWeekBucket,
    EquityPoint,
    HistogramBucket,
    HourBucket,
    InstrumentStats,
    StatsSummary,
    TimeBucket,
)
from services.outcomes import classify_outcome
from services.time_utils import compute_session_date


def _session_date_of(p: Position) -> date:
    return compute_session_date(datetime.fromtimestamp(p.entry_time, tz=UTC))


def compute_summary(positions: list[Position]) -> StatsSummary:
    """Headline summary. Input is the closed_with_pnl bucket only.

    `open_positions` and `skipped_no_multiplier` are filled in by the
    StatisticsService; here they are zero. Win-rate definition is canonical:
    wins / (wins + losses), scratches excluded, returns None if both are 0.
    """
    if not positions:
        return StatsSummary(
            total_positions=0,
            total_pnl=0.0,
            wins=0,
            losses=0,
            scratches=0,
            win_rate=None,
            avg_win=None,
            avg_loss=None,
            profit_factor=None,
            largest_win=None,
            largest_loss=None,
            longest_win_streak=0,
            longest_loss_streak=0,
            avg_hold_minutes=None,
            median_hold_minutes=None,
            avg_position_size=None,
            open_positions=0,
            skipped_no_multiplier=0,
        )

    winners: list[Position] = []
    losers: list[Position] = []
    scratches: list[Position] = []
    for p in positions:
        outcome = classify_outcome(p)
        if outcome == "winner":
            winners.append(p)
        elif outcome == "loser":
            losers.append(p)
        elif outcome == "scratch":
            scratches.append(p)

    win_pnls = [p.dollars_pnl for p in winners if p.dollars_pnl is not None]
    loss_pnls = [p.dollars_pnl for p in losers if p.dollars_pnl is not None]
    all_pnls = [p.dollars_pnl for p in positions if p.dollars_pnl is not None]
    total_pnl = sum(all_pnls)

    win_rate: float | None
    if winners or losers:
        win_rate = len(winners) / (len(winners) + len(losers))
    else:
        win_rate = None

    avg_win = (sum(win_pnls) / len(win_pnls)) if winners else None
    avg_loss = (sum(loss_pnls) / len(loss_pnls)) if losers else None
    largest_win = max(win_pnls) if winners else None
    largest_loss = min(loss_pnls) if losers else None

    profit_factor: float | None
    if losers:
        gross_loss = abs(sum(loss_pnls))
        if gross_loss > 0:
            profit_factor = sum(win_pnls) / gross_loss
        else:
            profit_factor = None
    else:
        profit_factor = None

    longest_win_streak, longest_loss_streak = _longest_streaks(positions)

    durations = [p.duration_minutes for p in positions if p.duration_minutes is not None]
    avg_hold = (sum(durations) / len(durations)) if durations else None
    med_hold = median(durations) if durations else None

    sizes = [p.quantity for p in positions]
    avg_size = (sum(sizes) / len(sizes)) if sizes else None

    return StatsSummary(
        total_positions=len(positions),
        total_pnl=total_pnl,
        wins=len(winners),
        losses=len(losers),
        scratches=len(scratches),
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        largest_win=largest_win,
        largest_loss=largest_loss,
        longest_win_streak=longest_win_streak,
        longest_loss_streak=longest_loss_streak,
        avg_hold_minutes=avg_hold,
        median_hold_minutes=med_hold,
        avg_position_size=avg_size,
        open_positions=0,
        skipped_no_multiplier=0,
    )


def _longest_streaks(positions: list[Position]) -> tuple[int, int]:
    """Walk closed positions in exit_time order. Scratches are skipped
    entirely (they neither extend nor break a streak), winners extend the
    win streak, losers extend the loss streak.
    """
    ordered = sorted(positions, key=lambda p: p.exit_time or 0)
    longest_win = 0
    longest_loss = 0
    cur_win = 0
    cur_loss = 0
    for p in ordered:
        outcome = classify_outcome(p)
        if outcome == "winner":
            cur_win += 1
            cur_loss = 0
            if cur_win > longest_win:
                longest_win = cur_win
        elif outcome == "loser":
            cur_loss += 1
            cur_win = 0
            if cur_loss > longest_loss:
                longest_loss = cur_loss
        # scratches and open positions: do nothing
    return longest_win, longest_loss


def bucket_by_session_date(
    positions: list[Position],
    *,
    granularity: Literal["day", "week", "month"],
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[TimeBucket]:
    """Bucket positions by their entry-time session date.

    Continuous fill: if `from_date`/`to_date` are given, the result has one
    bucket per granularity unit in [from_date, to_date]. Otherwise the range
    is derived from min..max session date in the input. Empty input with no
    range returns an empty list.

    Bucket key formats:
      day:   "YYYY-MM-DD"
      week:  "YYYY-Www" (ISO week, Monday-start)
      month: "YYYY-MM"
    """
    by_key: dict[str, tuple[int, float]] = {}
    session_dates: list[date] = []
    for p in positions:
        sd = _session_date_of(p)
        session_dates.append(sd)
        key = _format_bucket_key(sd, granularity)
        cnt, pnl_sum = by_key.get(key, (0, 0.0))
        by_key[key] = (cnt + 1, pnl_sum + (p.dollars_pnl or 0.0))

    if from_date is None and to_date is None and not session_dates:
        return []

    range_start = from_date if from_date is not None else min(session_dates)
    range_end = to_date if to_date is not None else max(session_dates)

    keys_in_order = _enumerate_keys(range_start, range_end, granularity)
    result: list[TimeBucket] = []
    for k in keys_in_order:
        cnt, pnl_sum = by_key.get(k, (0, 0.0))
        result.append(TimeBucket(bucket=k, position_count=cnt, total_pnl=pnl_sum))
    return result


def _format_bucket_key(d: date, granularity: str) -> str:
    if granularity == "day":
        return d.isoformat()
    if granularity == "week":
        iso_year, iso_week, _ = d.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if granularity == "month":
        return f"{d.year:04d}-{d.month:02d}"
    raise ValueError(f"unknown granularity: {granularity}")


def _enumerate_keys(start: date, end: date, granularity: str) -> list[str]:
    if granularity == "day":
        out = []
        cur = start
        while cur <= end:
            out.append(cur.isoformat())
            cur = cur + timedelta(days=1)
        return out
    if granularity == "week":
        # Walk Monday-aligned weeks from the ISO week containing `start` up to
        # and including the ISO week containing `end`.
        start_monday = start - timedelta(days=start.weekday())
        end_monday = end - timedelta(days=end.weekday())
        out = []
        cur = start_monday
        while cur <= end_monday:
            iso_year, iso_week, _ = cur.isocalendar()
            out.append(f"{iso_year}-W{iso_week:02d}")
            cur = cur + timedelta(days=7)
        return out
    if granularity == "month":
        out = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            out.append(f"{y:04d}-{m:02d}")
            m += 1
            if m == 13:
                m = 1
                y += 1
        return out
    raise ValueError(f"unknown granularity: {granularity}")


def bucket_by_hour(
    positions: list[Position],
    *,
    display_tz: ZoneInfo,
) -> list[HourBucket]:
    """24 buckets, one per hour of day in `display_tz`. Always continuous."""
    counts = [0] * 24
    pnls = [0.0] * 24
    for p in positions:
        local = datetime.fromtimestamp(p.entry_time, tz=display_tz)
        h = local.hour
        counts[h] += 1
        pnls[h] += p.dollars_pnl or 0.0
    return [HourBucket(hour=h, position_count=counts[h], total_pnl=pnls[h]) for h in range(24)]


def cumulative_equity(positions: list[Position]) -> list[EquityPoint]:
    """One point per session date, ordered ascending. The point value is the
    closing cumulative P&L at end of that day. Open positions (no exit_time /
    no dollars_pnl) are excluded. Time is YYYY-MM-DD (UTC date of exit_time)
    so TradingView renders a clean daily axis instead of mixing day numbers and
    HH:MM intraday labels."""
    closed = [p for p in positions if p.exit_time is not None and p.dollars_pnl is not None]
    closed.sort(key=lambda p: p.exit_time or 0)
    running = 0.0
    # Keep the last cumulative value seen for each date.
    by_date: dict[str, float] = {}
    for p in closed:
        running += p.dollars_pnl or 0.0
        date_str = datetime.fromtimestamp(p.exit_time or 0, tz=UTC).strftime("%Y-%m-%d")
        by_date[date_str] = running
    return [EquityPoint(time=d, cumulative_pnl=v) for d, v in sorted(by_date.items())]


def pnl_histogram(
    positions: list[Position],
    *,
    n_buckets: int = 10,
) -> list[HistogramBucket]:
    """Always returns `n_buckets` buckets spanning [min, max] of the inputs.

    Empty input -> empty list. Single value -> 10 evenly-spaced degenerate
    buckets between value-0.5 and value+0.5 (so the count lands in one bucket
    and the chart still has 10 bars).
    """
    pnls = [p.dollars_pnl for p in positions if p.dollars_pnl is not None]
    if not pnls:
        return []
    lo = min(pnls)
    hi = max(pnls)
    if lo == hi:
        lo -= 0.5
        hi += 0.5
    width = (hi - lo) / n_buckets
    edges = [lo + i * width for i in range(n_buckets + 1)]
    counts = [0] * n_buckets
    for v in pnls:
        idx = int((v - lo) / width)
        if idx >= n_buckets:
            idx = n_buckets - 1
        counts[idx] += 1
    return [
        HistogramBucket(bucket_min=edges[i], bucket_max=edges[i + 1], count=counts[i])
        for i in range(n_buckets)
    ]


def split_by_side(positions: list[Position]) -> tuple[list[Position], list[Position]]:
    longs = [p for p in positions if p.side == "Long"]
    shorts = [p for p in positions if p.side == "Short"]
    return longs, shorts


def per_instrument(positions: list[Position]) -> list[InstrumentStats]:
    by_inst: dict[str, list[Position]] = {}
    for p in positions:
        by_inst.setdefault(p.instrument, []).append(p)
    rows: list[InstrumentStats] = []
    for instrument, group in sorted(by_inst.items()):
        s = compute_summary(group)
        avg = s.total_pnl / s.total_positions if s.total_positions else 0.0
        rows.append(
            InstrumentStats(
                instrument=instrument,
                position_count=s.total_positions,
                total_pnl=s.total_pnl,
                win_rate=s.win_rate,
                avg_pnl_per_position=avg,
            )
        )
    return rows


_DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def bucket_by_day_of_week(positions: list[Position]) -> list[DayOfWeekBucket]:
    """Always returns 5 buckets (Mon–Fri), zero-filled for days with no trades.

    Uses session date (exchange-tz rollover) for weekday attribution so that
    a Sunday-evening entry at 17:00 CT maps to Monday, not Sunday.
    """
    pnl_sums = [0.0] * 5
    trade_counts = [0] * 5
    wins = [0] * 5
    losses = [0] * 5
    trading_day_sets: list[set] = [set() for _ in range(5)]

    for p in positions:
        sd = _session_date_of(p)
        dow = sd.weekday()  # 0=Mon … 6=Sun
        if dow > 4:  # skip weekend session dates (rare but possible)
            continue
        pnl_sums[dow] += p.dollars_pnl or 0.0
        trade_counts[dow] += 1
        trading_day_sets[dow].add(sd)
        outcome = classify_outcome(p)
        if outcome == "winner":
            wins[dow] += 1
        elif outcome == "loser":
            losses[dow] += 1

    result: list[DayOfWeekBucket] = []
    for dow in range(5):
        td = len(trading_day_sets[dow])
        w, l = wins[dow], losses[dow]
        result.append(
            DayOfWeekBucket(
                dow=dow,
                day_name=_DOW_NAMES[dow],
                trading_days=td,
                trades=trade_counts[dow],
                avg_pnl=pnl_sums[dow] / td if td > 0 else 0.0,
                win_rate=w / (w + l) if (w + l) > 0 else None,
                total_pnl=pnl_sums[dow],
            )
        )
    return result
