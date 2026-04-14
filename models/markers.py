from typing import Literal

from models.base import StrictModel

Side = Literal["Buy", "Sell"]


class Marker(StrictModel):
    """One arrow marker on the price chart, derived from one real execution.

    Plan 13 emits one Marker per real Execution row (deduplicated; never one
    per synthetic #close/#open split half). The label is the un-suffixed
    nt_execution_id, which is the same string the executions table renders in
    its row, so the chart-arrow ↔ table-row linking can match by label.
    """

    time: int          # unix seconds, UTC — the execution timestamp
    price: float       # the fill price
    side: Side
    quantity: int
    label: str         # the un-suffixed nt_execution_id
