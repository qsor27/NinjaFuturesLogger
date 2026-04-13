from pathlib import Path

from db import connect
from models.execution import Execution
from models.position import Position
from services.positions import build_positions


def _load_executions(
    db_path: Path | str,
    *,
    account: str | None = None,
    instrument: str | None = None,
) -> list[Execution]:
    sql = (
        "SELECT nt_execution_id, account, instrument, timestamp, side,"
        " original_action, quantity, price, commission, entry_exit,"
        " position_after, source_order_id, source_filename, imported_at "
        "FROM executions"
    )
    clauses: list[str] = []
    params: list[object] = []
    if account is not None:
        clauses.append("account = ?")
        params.append(account)
    if instrument is not None:
        clauses.append("instrument = ?")
        params.append(instrument)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY account, instrument, timestamp, nt_execution_id"

    conn = connect(db_path)
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()
    return [
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


def list_positions(
    db_path: Path | str,
    *,
    account: str | None = None,
    instrument: str | None = None,
) -> list[Position]:
    """Load executions per filters, group by (account, instrument), build positions."""
    executions = _load_executions(db_path, account=account, instrument=instrument)
    groups: dict[tuple[str, str], list[Execution]] = {}
    for e in executions:
        groups.setdefault((e.account, e.instrument), []).append(e)

    positions: list[Position] = []
    for _key, group in groups.items():
        p, _issues = build_positions(group)
        positions.extend(p)
    return positions


def get_position(
    db_path: Path | str,
    *,
    account: str,
    instrument: str,
    entry_execution_id: str,
) -> Position | None:
    positions = list_positions(db_path, account=account, instrument=instrument)
    for p in positions:
        if p.entry_execution_id == entry_execution_id:
            return p
    return None
