from dataclasses import dataclass
from typing import Literal, get_args

from models.base import StrictModel

PositionSide = Literal["Long", "Short"]
Severity = Literal["low", "medium", "high"]
EntryMethod = Literal["market_next_open", "limit_next_open", "manual", "unknown"]
ENTRY_METHODS: tuple[str, ...] = get_args(EntryMethod)
TrendAlignment = Literal["with_trend", "counter_trend", "not_gated"]
TREND_ALIGNMENTS: tuple[str, ...] = get_args(TrendAlignment)


class Position(StrictModel):
    account: str
    instrument: str
    entry_execution_id: str
    side: PositionSide
    entry_time: int
    exit_time: int | None
    quantity: int
    entry_price: float
    exit_price: float | None
    points_pnl: float | None
    dollars_pnl: float | None
    commission: float
    duration_minutes: float | None
    execution_ids: list[str]
    entry_method: EntryMethod = "unknown"
    trend_alignment: TrendAlignment = "not_gated"


class IntegrityIssue(StrictModel):
    account: str
    instrument: str
    execution_id: str
    severity: Severity
    type: str
    description: str


@dataclass
class Fill:
    """Internal walk-state fill. Never persisted.

    A Fill either wraps one real Execution 1:1, or is a synthesized sub-fill
    produced by the reversal splitter. The `execution_id` carries the
    `#close` / `#open` suffix for synthesized fills.
    """

    execution_id: str
    account: str
    instrument: str
    timestamp: int
    side: Literal["Buy", "Sell"]
    quantity: int
    price: float
    commission: float
    entry_exit: Literal["Entry", "Exit"]
    order_name: str | None = None
