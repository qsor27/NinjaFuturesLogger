from collections.abc import Sequence

from models.execution import Execution
from models.position import IntegrityIssue


def _parse_position_column(value: str) -> int | None:
    """Parse the exporter's Position column into signed running quantity.

    Returns None if the value cannot be interpreted. `-` means flat (0).
    `5 L` means +5, `3 S` means -3.
    """
    s = value.strip()
    if s == "-":
        return 0
    parts = s.split()
    if len(parts) != 2:
        return None
    qty_s, tag = parts
    try:
        qty = int(qty_s)
    except ValueError:
        return None
    if qty < 0:
        return None
    if tag == "L":
        return qty
    if tag == "S":
        return -qty
    return None


def cross_check_against_source_position_column(
    executions: Sequence[Execution],
) -> list[IntegrityIssue]:
    """Walk executions in sorted order and compare the exporter's Position
    column against the builder's own running quantity.

    The caller is expected to pass executions for a single (account, instrument)
    pair. This function sorts by (timestamp, nt_execution_id) to match
    build_positions.
    """
    issues: list[IntegrityIssue] = []
    running_qty = 0
    for ex in sorted(executions, key=lambda e: (e.timestamp, e.nt_execution_id)):
        signed = ex.quantity if ex.side == "Buy" else -ex.quantity
        running_qty += signed

        raw = ex.position_after
        if raw is None or raw == "":
            continue

        reported = _parse_position_column(raw)
        if reported is None:
            issues.append(
                IntegrityIssue(
                    account=ex.account,
                    instrument=ex.instrument,
                    execution_id=ex.nt_execution_id,
                    severity="high",
                    type="position_column_mismatch",
                    description=f"could not parse Position column value {raw!r}",
                )
            )
            continue

        if reported != running_qty:
            issues.append(
                IntegrityIssue(
                    account=ex.account,
                    instrument=ex.instrument,
                    execution_id=ex.nt_execution_id,
                    severity="high",
                    type="position_column_mismatch",
                    description=(
                        f"builder running qty {running_qty} disagrees with CSV "
                        f"Position column {raw!r} (parsed as {reported})"
                    ),
                )
            )
    return issues
