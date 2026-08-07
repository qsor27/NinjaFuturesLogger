import time as _time
from collections.abc import Sequence
from pathlib import Path as _Path

from db import transaction
from models.execution import Execution
from models.position import IntegrityIssue
from services.execution_db import load_executions
from services.execution_ordering import (
    order_executions_for_walk,
)
from services.execution_ordering import (
    parse_position_column as _parse_position_column,
)


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
    for ex in order_executions_for_walk(executions):
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


def run_integrity_diff(
    db_path: _Path | str,
    account: str,
    instrument: str,
) -> None:
    """Load executions for one pair, build positions + issues, diff DB.

    Plan 11's post-tick hook iterates affected `(account, instrument)` pairs
    and calls this once per pair.
    """
    # Deferred imports — services/positions imports from this module at its
    # top, so top-level imports here would create a cycle.
    from services.integrity_db import auto_resolve_missing, upsert_issue
    from services.positions import build_positions

    now = int(_time.time())
    executions = load_executions(db_path, account=account, instrument=instrument)
    _positions, issues = build_positions(executions)

    present: set[tuple[str, str]] = {(i.execution_id, i.type) for i in issues}

    with transaction(db_path) as conn:
        for issue in issues:
            upsert_issue(conn, issue, now=now)
        auto_resolve_missing(
            conn,
            account=account,
            instrument=instrument,
            present_keys=present,
            now=now,
        )
