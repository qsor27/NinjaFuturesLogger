from typing import Literal

from models.base import StrictModel

Side = Literal["Buy", "Sell"]
EntryExit = Literal["Entry", "Exit"]
TickStatus = Literal["ok", "partial", "failed"]


class Execution(StrictModel):
    nt_execution_id: str
    account: str
    instrument: str
    timestamp: int
    side: Side
    original_action: str
    quantity: int
    price: float
    commission: float
    entry_exit: EntryExit
    position_after: str | None
    source_order_id: str | None
    source_filename: str
    imported_at: int

    def model_post_init(self, _context) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


class RejectRecord(StrictModel):
    line_number: int
    raw_line: str
    reason: str


class TickResult(StrictModel):
    filename: str
    status: TickStatus
    lines_read: int
    rows_parsed: int
    rows_inserted: int
    rows_skipped_duplicate: int
    rows_rejected: int
    cursor_before: int
    cursor_after: int
    tick_id: int | None
    error: str | None
