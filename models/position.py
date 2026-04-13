from dataclasses import dataclass
from typing import Literal

from models.base import StrictModel

PositionSide = Literal["Long", "Short"]
Severity = Literal["low", "medium", "high"]


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
