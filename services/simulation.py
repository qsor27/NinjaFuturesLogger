"""Simulation Analysis engine — pure.

Replays closed positions as entry/exit events in time order. Rules evaluate
against counters that only *taken* trades feed; a halted trader skips entries.
Spec: docs/superpowers/specs/2026-09-09-simulation-analysis-design.md.

No SQL, no clock, no config. Inputs are closed positions with dollars_pnl
(the caller filters); anything else raises ValueError.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from models.position import Position
from models.simulation import (
    ByDayRow,
    RuleAttribution,
    SimulationBlock,
    SimulationDelta,
    SimulationInputs,
    SimulationResult,
    SimulationRule,
    SkippedSummary,
    SkippedTrade,
)
from models.statistics import StatsFilter
from services.outcomes import classify_outcome
from services.statistics_aggregations import compute_summary, cumulative_equity
from services.time_utils import compute_session_date, session_date_of

_ACTION_STRENGTH = {"pause_minutes": 0, "stop_session": 1, "stop_week": 2}
_ENTRY, _EXIT = 1, 0  # event kind marker

# Event ordering at equal timestamps: another position's exit (with exit_time >
# entry_time, i.e. non-zero duration) is processed before any entry, so a closing
# trade updates counters before a same-second entry is evaluated against them. But
# a position's own entry always precedes its own exit -- otherwise a zero-duration
# position (exit_time == entry_time, reachable since NinjaTrader timestamps are
# whole seconds) would have its exit discarded (key not yet in taken_keys) and its
# outcome would never feed any counter. Concretely: sort by
# (ts, cross_order, key, intra_order) where cross_order is 0 for a normal-duration
# exit (sorts first) and 1 for everything else (entries and zero-duration exits),
# and intra_order is 0 for entry / 1 for exit so a same-key pair keeps entry first.

PositionKey = tuple[str, str, str]


def _key(p: Position) -> PositionKey:
    return (p.account, p.instrument, p.entry_execution_id)


@dataclass
class _ScopeState:
    losses: int = 0
    wins: int = 0
    scratches: int = 0
    trades: int = 0
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    net_pnl: float = 0.0
    peak: float = 0.0

    @property
    def drawdown(self) -> float:
        return self.peak - self.net_pnl

    def record(self, outcome: str, pnl: float) -> None:
        self.trades += 1
        self.net_pnl += pnl
        self.peak = max(self.peak, self.net_pnl)
        if outcome == "loser":
            self.losses += 1
            self.consecutive_losses += 1
            self.consecutive_wins = 0
        elif outcome == "winner":
            self.wins += 1
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        else:
            self.scratches += 1
            self.consecutive_losses = 0
            self.consecutive_wins = 0

    def value(self, metric: str) -> float:
        return getattr(self, metric)


@dataclass
class _WalkState:
    scopes: dict[str, _ScopeState] = field(
        default_factory=lambda: {s: _ScopeState() for s in ("session", "week", "all")}
    )
    session: date | None = None
    week: tuple[int, int] | None = None
    halted_session_by: int | None = None
    halted_week_by: int | None = None
    paused_until: int | None = None
    paused_by: int | None = None


def _roll_scopes(state: _WalkState, ts: int) -> None:
    sd = compute_session_date(datetime.fromtimestamp(ts, tz=UTC))
    wk = (sd.isocalendar()[0], sd.isocalendar()[1])
    if state.session != sd:
        state.session = sd
        state.scopes["session"] = _ScopeState()
        state.halted_session_by = None
    if state.week != wk:
        state.week = wk
        state.scopes["week"] = _ScopeState()
        state.halted_week_by = None


def _active_halt(state: _WalkState, ts: int) -> int | None:
    if state.halted_week_by is not None:
        return state.halted_week_by
    if state.halted_session_by is not None:
        return state.halted_session_by
    if state.paused_until is not None and ts < state.paused_until:
        return state.paused_by
    return None


def _apply_actions(
    state: _WalkState, rules: list[SimulationRule], fired: list[int], ts: int
) -> int:
    """Apply the strongest action among fired rules; return the rule index credited."""
    winner = max(fired, key=lambda i: (_ACTION_STRENGTH[rules[i].action], -i))
    action = rules[winner].action
    if action == "stop_week":
        if state.halted_week_by is None:
            state.halted_week_by = winner
    elif action == "stop_session":
        if state.halted_session_by is None:
            state.halted_session_by = winner
    else:
        until = ts + int(rules[winner].action_param or 0) * 60
        if state.paused_until is None or until > state.paused_until:
            state.paused_until = until
            state.paused_by = winner
    return winner


def _compare(value: float, comparator: str, threshold: float) -> bool:
    return value >= threshold if comparator == ">=" else value <= threshold


def _hhmm_to_minutes(s: str) -> int:
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)


def _local_minutes(ts: int, tz: ZoneInfo) -> int:
    local = datetime.fromtimestamp(ts, tz=UTC).astimezone(tz)
    return local.hour * 60 + local.minute


def max_drawdown(positions: list[Position]) -> float:
    """Largest peak-to-trough decline of cumulative P&L ordered by exit time. Peak starts at 0."""
    ordered = sorted(positions, key=lambda p: (p.exit_time or 0, _key(p)))
    running = peak = worst = 0.0
    for p in ordered:
        running += p.dollars_pnl or 0.0
        peak = max(peak, running)
        worst = max(worst, peak - running)
    return worst


def _block(positions: list[Position]) -> SimulationBlock:
    return SimulationBlock(
        summary=compute_summary(positions),
        max_drawdown=max_drawdown(positions),
        equity=cumulative_equity(positions),
    )


def _nullable_delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return b - a


def run_simulation(
    positions: list[Position],
    rules: list[SimulationRule],
    *,
    display_tz: ZoneInfo,
    filter: StatsFilter,
) -> SimulationResult:
    for p in positions:
        if p.exit_time is None or p.dollars_pnl is None:
            raise ValueError(
                f"run_simulation requires closed positions with P&L: {p.entry_execution_id}"
            )

    events: list[tuple[int, int, PositionKey, Position]] = []
    for p in positions:
        events.append((p.entry_time, _ENTRY, _key(p), p))
        events.append((int(p.exit_time or 0), _EXIT, _key(p), p))

    def _sort_key(e: tuple[int, int, PositionKey, Position]) -> tuple[int, int, PositionKey, int]:
        ts, kind, key, p = e
        if kind == _EXIT and (p.exit_time or 0) > p.entry_time:
            cross_order = 0  # normal-duration exit: ahead of any entry at this ts
        else:
            cross_order = 1  # entry, or a zero-duration position's own exit
        intra_order = 0 if kind == _ENTRY else 1
        return (ts, cross_order, key, intra_order)

    events.sort(key=_sort_key)

    entry_rules = [i for i, r in enumerate(rules) if r.metric == "time_of_day"]
    exit_rules = [i for i, r in enumerate(rules) if r.metric != "time_of_day"]

    state = _WalkState()
    fires = [0] * len(rules)
    taken: list[Position] = []
    taken_keys: set[PositionKey] = set()
    skipped_pairs: list[tuple[Position, int]] = []

    for ts, kind, key, p in events:
        _roll_scopes(state, ts)
        if kind == _ENTRY:
            blocker = _active_halt(state, ts)
            if blocker is None and entry_rules:
                minutes = _local_minutes(ts, display_tz)
                fired = [
                    i
                    for i in entry_rules
                    if _compare(
                        minutes, rules[i].comparator, _hhmm_to_minutes(str(rules[i].threshold))
                    )
                ]
                for i in fired:
                    fires[i] += 1
                if fired:
                    blocker = _apply_actions(state, rules, fired, ts)
            if blocker is None:
                taken.append(p)
                taken_keys.add(key)
            else:
                skipped_pairs.append((p, blocker))
        else:
            if key not in taken_keys:
                continue
            outcome = classify_outcome(p)
            pnl = float(p.dollars_pnl or 0.0)
            for scope_state in state.scopes.values():
                scope_state.record(outcome, pnl)
            fired = [
                i
                for i in exit_rules
                if _compare(
                    state.scopes[rules[i].scope].value(rules[i].metric),
                    rules[i].comparator,
                    float(rules[i].threshold),  # type: ignore[arg-type]
                )
            ]
            for i in fired:
                fires[i] += 1
            if fired:
                _apply_actions(state, rules, fired, ts)

    return _assemble(positions, rules, taken, taken_keys, skipped_pairs, fires, display_tz, filter)


def _assemble(
    positions: list[Position],
    rules: list[SimulationRule],
    taken: list[Position],
    taken_keys: set[PositionKey],
    skipped_pairs: list[tuple[Position, int]],
    fires: list[int],
    display_tz: ZoneInfo,
    filter: StatsFilter,
) -> SimulationResult:
    skipped_pairs.sort(key=lambda pr: (pr[0].entry_time, _key(pr[0])))
    skipped: list[SkippedTrade] = []
    losers = winners = scratches = 0
    losers_pnl = winners_pnl = 0.0
    per_rule_skips = [0] * len(rules)
    per_rule_pnl = [0.0] * len(rules)
    for p, idx in skipped_pairs:
        outcome = classify_outcome(p)
        pnl = float(p.dollars_pnl or 0.0)
        if outcome == "loser":
            losers += 1
            losers_pnl += pnl
        elif outcome == "winner":
            winners += 1
            winners_pnl += pnl
        else:
            scratches += 1
        per_rule_skips[idx] += 1
        per_rule_pnl[idx] += pnl
        skipped.append(
            SkippedTrade(
                account=p.account,
                instrument=p.instrument,
                entry_execution_id=p.entry_execution_id,
                entry_time=p.entry_time,
                exit_time=int(p.exit_time or 0),
                dollars_pnl=pnl,
                outcome=outcome,  # type: ignore[arg-type]
                rule_index=idx,
            )
        )

    by_day_acc: dict[date, dict] = {}
    for p in positions:
        row = by_day_acc.setdefault(
            session_date_of(p), {"actual": 0.0, "sim": 0.0, "skipped": 0, "rules": set()}
        )
        pnl = float(p.dollars_pnl or 0.0)
        row["actual"] += pnl
        if _key(p) in taken_keys:
            row["sim"] += pnl
    for p, idx in skipped_pairs:
        row = by_day_acc[session_date_of(p)]
        row["skipped"] += 1
        row["rules"].add(idx)
    by_day = [
        ByDayRow(
            session_date=sd,
            actual_pnl=row["actual"],
            simulated_pnl=row["sim"],
            skipped_count=row["skipped"],
            rules_fired=sorted(row["rules"]),
        )
        for sd, row in sorted(by_day_acc.items())
        if row["skipped"] > 0
    ]

    actual = _block(positions)
    simulated = _block(taken)
    delta = SimulationDelta(
        total_pnl=simulated.summary.total_pnl - actual.summary.total_pnl,
        total_positions=simulated.summary.total_positions - actual.summary.total_positions,
        wins=simulated.summary.wins - actual.summary.wins,
        losses=simulated.summary.losses - actual.summary.losses,
        win_rate=_nullable_delta(actual.summary.win_rate, simulated.summary.win_rate),
        profit_factor=_nullable_delta(
            actual.summary.profit_factor, simulated.summary.profit_factor
        ),
        max_drawdown=simulated.max_drawdown - actual.max_drawdown,
    )
    return SimulationResult(
        inputs=SimulationInputs(
            accounts=filter.accounts,
            from_date=filter.from_date,
            to_date=filter.to_date,
            side=filter.side,
            positions_considered=len(positions),
            display_tz=str(display_tz),
            rules=rules,
        ),
        actual=actual,
        simulated=simulated,
        delta=delta,
        skipped=skipped,
        skipped_summary=SkippedSummary(
            count=len(skipped),
            losers=losers,
            losers_pnl=losers_pnl,
            winners=winners,
            winners_pnl=winners_pnl,
            scratches=scratches,
        ),
        rule_attribution=[
            RuleAttribution(
                rule_index=i,
                label=r.label,
                fires=fires[i],
                skipped_trades=per_rule_skips[i],
                skipped_pnl=per_rule_pnl[i],
            )
            for i, r in enumerate(rules)
        ],
        by_day=by_day,
    )
