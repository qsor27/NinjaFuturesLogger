"""Pure aggregation helpers for plan 15 statistics.

Every function here is referentially transparent: takes data, returns data,
no I/O, no globals, no clock. Each helper is unit-tested in isolation in
tests/test_statistics_aggregations.py. The StatisticsService is only a
thin I/O wrapper that calls these.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from statistics import median

from models.position import Position
from models.statistics import StatsSummary
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
