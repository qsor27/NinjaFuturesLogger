"""Simulation Analysis contracts.

Spec: docs/superpowers/specs/2026-09-09-simulation-analysis-design.md.
Every rule is validated here once; the engine trusts validated rules.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal, get_args

from pydantic import Field, model_validator

from models.base import StrictModel
from models.position import EntryMethod, TrendAlignment
from models.statistics import EquityPoint, StatsSummary

Metric = Literal[
    "losses",
    "wins",
    "scratches",
    "trades",
    "consecutive_losses",
    "consecutive_wins",
    "net_pnl",
    "drawdown",
    "time_of_day",
]
Scope = Literal["session", "week", "all"]
Comparator = Literal[">=", "<="]
Action = Literal["stop_session", "stop_week", "pause_minutes"]
ThresholdType = Literal["count", "dollars", "time"]

METRICS: tuple[str, ...] = get_args(Metric)
SCOPES: tuple[str, ...] = get_args(Scope)
COMPARATORS: tuple[str, ...] = get_args(Comparator)
ACTIONS: tuple[str, ...] = get_args(Action)

COUNT_METRICS = frozenset(
    {"losses", "wins", "scratches", "trades", "consecutive_losses", "consecutive_wins"}
)
DOLLAR_METRICS = frozenset({"net_pnl", "drawdown"})
TIME_METRICS = frozenset({"time_of_day"})

METRIC_LABELS: dict[str, str] = {
    "losses": "losses",
    "wins": "wins",
    "scratches": "scratches",
    "trades": "trades",
    "consecutive_losses": "consecutive losses",
    "consecutive_wins": "consecutive wins",
    "net_pnl": "net P&L",
    "drawdown": "drawdown",
    "time_of_day": "entry time",
}
SCOPE_LABELS: dict[str, str] = {"session": "session", "week": "week", "all": "all time"}
COMPARATOR_LABELS: dict[str, str] = {">=": "at least", "<=": "at most"}
ACTION_LABELS: dict[str, str] = {
    "stop_session": "stop for session",
    "stop_week": "stop for week",
    "pause_minutes": "pause",
}

MAX_RULES = 10
MAX_PAUSE_MINUTES = 1440
_HHMM = re.compile(r"^\d{2}:\d{2}$")


def threshold_type(metric: str) -> ThresholdType:
    if metric in COUNT_METRICS:
        return "count"
    if metric in DOLLAR_METRICS:
        return "dollars"
    return "time"


def _fmt_dollars(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


class SimulationRule(StrictModel):
    metric: Metric
    scope: Scope
    comparator: Comparator
    threshold: int | float | str
    action: Action
    action_param: int | None = None
    label: str = ""  # always regenerated server-side

    @model_validator(mode="after")
    def _validate(self) -> SimulationRule:
        t = self.threshold
        kind = threshold_type(self.metric)
        if kind == "count":
            if isinstance(t, bool) or not isinstance(t, int) or t < 0:
                raise ValueError(f"{self.metric} threshold must be a non-negative integer")
        elif kind == "dollars":
            if isinstance(t, bool) or not isinstance(t, int | float):
                raise ValueError(f"{self.metric} threshold must be a dollar amount")
            self.threshold = float(t)
        else:
            if not isinstance(t, str) or not _HHMM.fullmatch(t):
                raise ValueError("time_of_day threshold must be HH:MM")
            hh, mm = (int(x) for x in t.split(":"))
            if hh > 23 or mm > 59:
                raise ValueError("time_of_day threshold must be a valid HH:MM")
            if self.scope != "session":
                raise ValueError("time_of_day rules must use scope 'session'")
        if self.action == "pause_minutes":
            if self.action_param is None or not (1 <= self.action_param <= MAX_PAUSE_MINUTES):
                raise ValueError(f"pause_minutes needs action_param 1..{MAX_PAUSE_MINUTES}")
        elif self.action_param is not None:
            raise ValueError("action_param only applies to pause_minutes")
        self.label = rule_label(self)
        return self


def rule_label(rule: SimulationRule) -> str:
    """Human sentence for a rule. The frontend never composes labels."""
    kind = threshold_type(rule.metric)
    if kind == "time":
        cond = f"entry time {rule.comparator} {rule.threshold}"
    elif kind == "dollars":
        cond = (
            f"{METRIC_LABELS[rule.metric]} in {SCOPE_LABELS[rule.scope]} "
            f"{rule.comparator} {_fmt_dollars(float(rule.threshold))}"
        )
    else:
        cond = (
            f"{METRIC_LABELS[rule.metric]} in {SCOPE_LABELS[rule.scope]} "
            f"{rule.comparator} {rule.threshold}"
        )
    if rule.action == "pause_minutes":
        act = f"pause {rule.action_param} min"
    else:
        act = ACTION_LABELS[rule.action]
    return f"{cond} -> {act}"


def vocabulary() -> dict:
    """Menu payload for the builder. Test asserts it mirrors the Literal enums."""
    return {
        "metrics": [
            {
                "value": m,
                "label": METRIC_LABELS[m],
                "threshold_type": threshold_type(m),
                "scopes": ["session"] if m in TIME_METRICS else list(SCOPES),
            }
            for m in METRICS
        ],
        "scopes": [{"value": s, "label": SCOPE_LABELS[s]} for s in SCOPES],
        "comparators": [{"value": c, "label": COMPARATOR_LABELS[c]} for c in COMPARATORS],
        "actions": [
            {"value": a, "label": ACTION_LABELS[a], "needs_param": a == "pause_minutes"}
            for a in ACTIONS
        ],
        "max_rules": MAX_RULES,
        "max_pause_minutes": MAX_PAUSE_MINUTES,
    }


class SimulationDefinitionInput(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    rules: list[SimulationRule] = Field(min_length=1, max_length=MAX_RULES)

    @model_validator(mode="after")
    def _strip_name(self) -> SimulationDefinitionInput:
        stripped = self.name.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        self.name = stripped
        return self


class SimulationDefinition(StrictModel):
    simulation_id: int
    name: str
    rules: list[SimulationRule]
    created_at: int
    updated_at: int


class SimulationRunRequest(StrictModel):
    rules: list[SimulationRule] = Field(min_length=1, max_length=MAX_RULES)
    accounts: tuple[str, ...] = ()
    from_date: date | None = None
    to_date: date | None = None
    side: Literal["Long", "Short"] | None = None
    entry_method: EntryMethod | None = None
    trend_alignment: TrendAlignment | None = None


class SimulationBlock(StrictModel):
    summary: StatsSummary
    max_drawdown: float
    equity: list[EquityPoint]


class SimulationDelta(StrictModel):
    total_pnl: float
    total_positions: int
    wins: int
    losses: int
    win_rate: float | None
    profit_factor: float | None
    max_drawdown: float


class SimulationInputs(StrictModel):
    accounts: tuple[str, ...]
    from_date: date | None
    to_date: date | None
    side: Literal["Long", "Short"] | None
    positions_considered: int
    display_tz: str
    rules: list[SimulationRule]


class SkippedTrade(StrictModel):
    account: str
    instrument: str
    entry_execution_id: str
    entry_time: int
    exit_time: int
    dollars_pnl: float
    outcome: Literal["winner", "loser", "scratch"]
    rule_index: int


class SkippedSummary(StrictModel):
    count: int
    losers: int
    losers_pnl: float
    winners: int
    winners_pnl: float
    scratches: int


class RuleAttribution(StrictModel):
    rule_index: int
    label: str
    fires: int
    skipped_trades: int
    skipped_pnl: float


class ByDayRow(StrictModel):
    session_date: date
    actual_pnl: float
    simulated_pnl: float
    skipped_count: int
    rules_fired: list[int]


class SimulationResult(StrictModel):
    inputs: SimulationInputs
    actual: SimulationBlock
    simulated: SimulationBlock
    delta: SimulationDelta
    skipped: list[SkippedTrade]
    skipped_summary: SkippedSummary
    rule_attribution: list[RuleAttribution]
    by_day: list[ByDayRow]
