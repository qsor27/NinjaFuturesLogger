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


import time as _time
from pathlib import Path as _Path

from db import connect as _connect


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
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit,"
            " position_after, source_order_id, source_filename, imported_at "
            "FROM executions WHERE account = ? AND instrument = ? "
            "ORDER BY timestamp, nt_execution_id",
            (account, instrument),
        ).fetchall()
        executions = [
            Execution(
                nt_execution_id=r["nt_execution_id"],
                account=r["account"],
                instrument=r["instrument"],
                timestamp=r["timestamp"],
                side=r["side"],
                original_action=r["original_action"],
                quantity=r["quantity"],
                price=r["price"],
                commission=r["commission"],
                entry_exit=r["entry_exit"],
                position_after=r["position_after"],
                source_order_id=r["source_order_id"],
                source_filename=r["source_filename"],
                imported_at=r["imported_at"],
            )
            for r in rows
        ]
        _positions, issues = build_positions(executions)

        present: set[tuple[str, str]] = {(i.execution_id, i.type) for i in issues}

        conn.execute("BEGIN")
        try:
            for issue in issues:
                upsert_issue(conn, issue, now=now)
            auto_resolve_missing(
                conn,
                account=account,
                instrument=instrument,
                present_keys=present,
                now=now,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
