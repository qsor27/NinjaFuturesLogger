from typing import Literal

from models.base import StrictModel
from models.position import PositionSide

ReviewCall = Literal["valid", "invalid"]


class ReviewCard(StrictModel):
    """One drill card = one closed, 1m-covered position."""

    account: str
    instrument: str
    entry_execution_id: str
    entry_time: int
    side: PositionSide
    quantity: int
    entry_price: float


class RevealFill(StrictModel):
    time: int
    price: float
    side: Literal["Buy", "Sell"]
    quantity: int


class RevealPayload(StrictModel):
    net_pnl: float
    dollars_pnl: float
    commission: float
    exit_time: int
    exit_fills: list[RevealFill]


class SummaryCell(StrictModel):
    count: int
    net_pnl: float


class ReviewSummary(StrictModel):
    valid_won: SummaryCell
    valid_lost: SummaryCell
    valid_scratch: SummaryCell
    invalid_won: SummaryCell
    invalid_lost: SummaryCell
    invalid_scratch: SummaryCell
    attempts: int
