from collections.abc import Sequence

from models.execution import Execution
from models.position import Fill, IntegrityIssue, Position
from services.instruments import get_multiplier


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def _fill_from(ex: Execution) -> Fill:
    return Fill(
        execution_id=ex.nt_execution_id,
        account=ex.account,
        instrument=ex.instrument,
        timestamp=ex.timestamp,
        side=ex.side,
        quantity=ex.quantity,
        price=ex.price,
        commission=ex.commission,
        entry_exit=ex.entry_exit,
    )


def _make_position(fills: list[Fill], *, is_open: bool) -> Position:
    first = fills[0]
    side = "Long" if first.side == "Buy" else "Short"

    if side == "Long":
        entry_fills = [f for f in fills if f.side == "Buy"]
        exit_fills = [f for f in fills if f.side == "Sell"]
    else:
        entry_fills = [f for f in fills if f.side == "Sell"]
        exit_fills = [f for f in fills if f.side == "Buy"]

    entry_qty_total = sum(f.quantity for f in entry_fills)
    entry_price = (
        sum(f.price * f.quantity for f in entry_fills) / entry_qty_total
        if entry_qty_total
        else 0.0
    )

    if is_open or not exit_fills:
        exit_time: int | None = None
        exit_price: float | None = None
        points_pnl: float | None = None
        dollars_pnl: float | None = None
        duration_minutes: float | None = None
    else:
        exit_qty_total = sum(f.quantity for f in exit_fills)
        exit_price = (
            sum(f.price * f.quantity for f in exit_fills) / exit_qty_total
            if exit_qty_total
            else 0.0
        )
        exit_time = fills[-1].timestamp
        signed_qty = entry_qty_total if side == "Long" else -entry_qty_total
        points_pnl = (exit_price - entry_price) * signed_qty
        dollars_pnl = points_pnl * get_multiplier(first.instrument)
        duration_minutes = (exit_time - first.timestamp) / 60.0

    return Position(
        account=first.account,
        instrument=first.instrument,
        entry_execution_id=entry_fills[0].execution_id,
        side=side,
        entry_time=first.timestamp,
        exit_time=exit_time,
        quantity=entry_qty_total,
        entry_price=entry_price,
        exit_price=exit_price,
        points_pnl=points_pnl,
        dollars_pnl=dollars_pnl,
        commission=sum(f.commission for f in fills),
        duration_minutes=duration_minutes,
        execution_ids=[f.execution_id for f in fills],
    )


def build_positions(
    executions: Sequence[Execution],
) -> tuple[list[Position], list[IntegrityIssue]]:
    """Pure function: walk executions and emit positions.

    Direction-reversing fills and sort stability are handled in later tasks.
    """
    positions: list[Position] = []
    issues: list[IntegrityIssue] = []
    current: list[Fill] = []
    running_qty = 0

    for ex in executions:
        signed = ex.quantity if ex.side == "Buy" else -ex.quantity
        new_qty = running_qty + signed
        current.append(_fill_from(ex))
        running_qty = new_qty

        if running_qty == 0:
            positions.append(_make_position(current, is_open=False))
            current = []

    if current:
        positions.append(_make_position(current, is_open=True))

    return positions, issues
