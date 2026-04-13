import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from models.execution import Execution

_VALID_ACTIONS = {"Buy", "Sell", "BuyToCover", "SellShort"}
_ACTION_TO_SIDE = {
    "Buy": "Buy",
    "BuyToCover": "Buy",
    "Sell": "Sell",
    "SellShort": "Sell",
}
_EXPECTED_COLS = 15
_TIME_FORMAT = "%m/%d/%Y %I:%M:%S %p"


class ParseError(ValueError):
    """Raised for any per-row parse failure. The message becomes import_rejects.reason."""


def parse_execution_row(
    line: str,
    *,
    source_filename: str,
    trader_tz: ZoneInfo,
    imported_at: int,
) -> Execution:
    """Parse one line of the ExecutionExporter.cs CSV format (doc 90)."""
    try:
        fields = next(csv.reader(io.StringIO(line)))
    except StopIteration as e:
        raise ParseError("empty line") from e

    if len(fields) != _EXPECTED_COLS:
        raise ParseError(f"expected {_EXPECTED_COLS} columns, got {len(fields)}")

    (
        instrument,
        action,
        qty_s,
        price_s,
        time_s,
        exec_id,
        entry_exit,
        position,
        order_id,
        _name,
        commission_s,
        _rate,
        account,
        _connection,
        _validation,
    ) = fields

    if action not in _VALID_ACTIONS:
        raise ParseError(f"invalid action: {action!r}")
    side = _ACTION_TO_SIDE[action]

    try:
        quantity = int(qty_s)
    except ValueError as e:
        raise ParseError(f"invalid quantity: {qty_s!r}") from e
    if quantity <= 0:
        raise ParseError(f"non-positive quantity: {quantity}")

    try:
        price = float(price_s)
    except ValueError as e:
        raise ParseError(f"invalid price: {price_s!r}") from e

    try:
        local_naive = datetime.strptime(time_s, _TIME_FORMAT)
    except ValueError as e:
        raise ParseError(f"invalid time: {time_s!r}") from e
    local_aware = local_naive.replace(tzinfo=trader_tz)
    timestamp = int(local_aware.timestamp())

    if entry_exit not in {"Entry", "Exit"}:
        raise ParseError(f"invalid E/X: {entry_exit!r}")

    commission_clean = commission_s.lstrip("$").strip() or "0"
    try:
        commission = float(commission_clean)
    except ValueError as e:
        raise ParseError(f"invalid commission: {commission_s!r}") from e

    if not exec_id:
        raise ParseError("empty execution id")
    if not account:
        raise ParseError("empty account")

    return Execution(
        nt_execution_id=exec_id,
        account=account,
        instrument=instrument,
        timestamp=timestamp,
        side=side,
        original_action=action,
        quantity=quantity,
        price=price,
        commission=commission,
        entry_exit=entry_exit,
        position_after=(position or None),
        source_order_id=(order_id or None),
        source_filename=source_filename,
        imported_at=imported_at,
    )
