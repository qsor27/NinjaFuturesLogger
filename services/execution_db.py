"""Canonical executions-table access: the one column list, one row->model
hydration, and one loader (review D1). Adding a column to `executions` means
editing EXECUTION_COLUMNS + execution_from_row here and nowhere else.
"""

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from db import read_conn, sql_placeholders
from models.execution import Execution
from services.notes import strip_split_suffix

EXECUTION_COLUMNS: str = (
    "nt_execution_id, account, instrument, timestamp, side,"
    " original_action, quantity, price, commission, entry_exit,"
    " position_after, source_order_id, source_filename, imported_at, order_name"
)


def execution_from_row(row: sqlite3.Row) -> Execution:
    """Hydrate one EXECUTION_COLUMNS row into an Execution model."""
    return Execution(
        nt_execution_id=row["nt_execution_id"],
        account=row["account"],
        instrument=row["instrument"],
        timestamp=row["timestamp"],
        side=row["side"],
        original_action=row["original_action"],
        quantity=row["quantity"],
        price=row["price"],
        commission=row["commission"],
        entry_exit=row["entry_exit"],
        position_after=row["position_after"],
        source_order_id=row["source_order_id"],
        source_filename=row["source_filename"],
        imported_at=row["imported_at"],
        order_name=row["order_name"],
    )


def load_executions(
    db_path: Path | str,
    *,
    account: str | None = None,
    instrument: str | None = None,
    accounts: Sequence[str] | None = None,
) -> list[Execution]:
    """Load executions as models, ordered (account, instrument, timestamp,
    nt_execution_id).

    Filters: `account` (single, SQL pushdown), `accounts` (IN-list; None or
    empty means no account filter), `instrument`. `account` and `accounts`
    are mutually exclusive. When both account and instrument are pinned, the
    canonical ORDER BY is identical to the walk order
    (timestamp, nt_execution_id) used by build_positions.
    """
    if account is not None and accounts:
        raise ValueError("pass account or accounts, not both")
    sql = f"SELECT {EXECUTION_COLUMNS} FROM executions"
    clauses: list[str] = []
    params: list[object] = []
    if account is not None:
        clauses.append("account = ?")
        params.append(account)
    if accounts:
        clauses.append(f"account IN ({sql_placeholders(len(accounts))})")
        params.extend(accounts)
    if instrument is not None:
        clauses.append("instrument = ?")
        params.append(instrument)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY account, instrument, timestamp, nt_execution_id"
    with read_conn(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [execution_from_row(r) for r in rows]


def execution_exists(db_path: Path | str, execution_id: str) -> bool:
    """True if a real execution row exists for this ID. Split-fill suffixes
    (#close/#open) are stripped first, matching all user-metadata routes."""
    real_id = strip_split_suffix(execution_id)
    with read_conn(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM executions WHERE nt_execution_id = ?",
            (real_id,),
        ).fetchone()
    return row is not None
