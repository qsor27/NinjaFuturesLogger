from pathlib import Path

from db import connect
from models.browsing import PageMeta, PositionListPage
from models.execution import Execution
from models.position import Position
from services.flags import list_flags_for_executions
from services.notes import list_notes_for_executions
from services.position_filters import PositionFilter, apply_filters, paginate
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


def list_positions_page(
    db_path: Path | str,
    *,
    filter_: PositionFilter,
    page: int,
    page_size: int,
) -> PositionListPage:
    """Compute positions for the scope implied by the filter, apply all
    remaining filters, sort newest-first by entry_time, and paginate.

    Rule 4 from doc 12: this function recomputes positions on every call.
    No cache, no materialization.
    """
    executions = _load_executions(
        db_path,
        account=filter_.account,
        instrument=filter_.instrument,
    )
    groups: dict[tuple[str, str], list] = {}
    for e in executions:
        groups.setdefault((e.account, e.instrument), []).append(e)

    all_positions = []
    for _key, group in groups.items():
        ps, _issues = build_positions(group)
        all_positions.extend(ps)

    all_positions.sort(key=lambda p: p.entry_time, reverse=True)
    filtered = apply_filters(all_positions, filter_)
    slice_, total = paginate(filtered, page=page, page_size=page_size)
    return PositionListPage(
        positions=slice_,
        page=PageMeta(page=max(1, page), page_size=max(1, page_size), total=total),
    )


def get_filter_options(db_path: Path | str) -> dict:
    """Return the set of accounts and instruments that currently have any
    execution in the database."""
    conn = connect(db_path)
    try:
        accounts = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT account FROM executions ORDER BY account"
            ).fetchall()
        ]
        instruments = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT instrument FROM executions ORDER BY instrument"
            ).fetchall()
        ]
    finally:
        conn.close()
    return {"accounts": accounts, "instruments": instruments}


def attach_metadata(db_path: Path | str, position) -> dict:
    """Return the detail-response envelope for one position."""
    from services.custom_fields import CustomFieldsService

    notes = list_notes_for_executions(db_path, position.execution_ids)
    reviewed = list_flags_for_executions(db_path, position.execution_ids)
    svc = CustomFieldsService(db_path)
    custom_fields = svc.values_for_position(
        execution_ids=position.execution_ids,
        entry_execution_id=position.entry_execution_id,
    )
    return {
        "position": position.model_dump(),
        "notes": notes,
        "reviewed": reviewed,
        "custom_fields": custom_fields,
    }
