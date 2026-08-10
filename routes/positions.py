import time

from flask import Blueprint, jsonify, request

from db import read_conn, sql_placeholders, transaction
from logging_config import get_logger
from models.execution import Execution
from routes import db_path as _db_path
from routes._params import BadParam, int_arg
from services.execution_db import load_executions
from services.instruments import effective_commission, get_multiplier
from services.integrity_db import mark_ignored, mark_resolved_by_user
from services.markers import build_markers
from services.notes import strip_split_suffix
from services.position_filters import PositionFilter
from services.positions_service import (
    attach_metadata,
    get_filter_options,
    get_position,
    get_position_with_fills,
    list_positions_page,
)

log = get_logger("http.positions")


def _position_executions(db_path, position) -> list[Execution]:
    """All real executions belonging to a position, in walk order.

    Split-fill suffixes in position.execution_ids are stripped so the
    synthesized #close/#open halves match their parent row.
    """
    wanted = {strip_split_suffix(eid) for eid in position.execution_ids}
    return [
        e
        for e in load_executions(db_path, account=position.account, instrument=position.instrument)
        if e.nt_execution_id in wanted
    ]


def _parse_filter_from_query(args) -> PositionFilter:
    from datetime import date
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    accounts = tuple(a for a in args.getlist("account") if a)
    instrument = args.get("instrument") or None

    side = args.get("side") or None
    if side is not None and side not in ("Long", "Short"):
        raise ValueError(f"side must be Long or Short, got {side!r}")

    outcome = args.get("outcome") or None
    if outcome is not None and outcome not in ("winner", "loser", "scratch", "open"):
        raise ValueError(f"outcome must be winner, loser, scratch, or open, got {outcome!r}")

    def _int_or_none(key: str) -> int | None:
        v = args.get(key)
        if v is None or v == "":
            return None
        try:
            return int(v)
        except ValueError as e:
            raise ValueError(f"{key} must be an integer") from e

    def _date_or_none(key: str) -> date | None:
        v = args.get(key)
        if v is None or v == "":
            return None
        try:
            return date.fromisoformat(v)
        except ValueError as e:
            raise ValueError(f"{key} must be ISO YYYY-MM-DD") from e

    session_date_from = _date_or_none("session_date_from")
    session_date_to = _date_or_none("session_date_to")
    if (
        session_date_from is not None
        and session_date_to is not None
        and session_date_from > session_date_to
    ):
        raise ValueError("session_date_from must be <= session_date_to")

    day_of_week = _int_or_none("day_of_week")
    if day_of_week is not None and not (0 <= day_of_week <= 4):
        raise ValueError("day_of_week must be 0..4 (Mon..Fri)")

    hour_of_day = _int_or_none("hour_of_day")
    if hour_of_day is not None and not (0 <= hour_of_day <= 23):
        raise ValueError("hour_of_day must be 0..23")

    hour_tz = args.get("hour_tz") or None
    if hour_tz is not None:
        try:
            ZoneInfo(hour_tz)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"hour_tz is not a valid IANA timezone: {hour_tz!r}") from e
    if hour_of_day is not None and hour_tz is None:
        raise ValueError("hour_of_day requires hour_tz")

    trades_per_day = _int_or_none("trades_per_day")
    if trades_per_day is not None and trades_per_day < 1:
        raise ValueError("trades_per_day must be >= 1")

    return PositionFilter(
        accounts=accounts,
        instrument=instrument,
        side=side,
        outcome=outcome,
        entry_time_min=_int_or_none("entry_time_min"),
        entry_time_max=_int_or_none("entry_time_max"),
        session_date_from=session_date_from,
        session_date_to=session_date_to,
        day_of_week=day_of_week,
        hour_of_day=hour_of_day,
        hour_tz=hour_tz,
        trades_per_day=trades_per_day,
    )


def build_positions_blueprint() -> Blueprint:
    bp = Blueprint("positions", __name__)

    @bp.get("/api/positions")
    def list_endpoint():
        try:
            filter_ = _parse_filter_from_query(request.args)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        try:
            page = int_arg(request.args, "page", default=1, lo=1)
            page_size = int_arg(request.args, "page_size", default=50, lo=1, hi=500)
        except BadParam as e:
            return jsonify({"error": str(e)}), 400
        result = list_positions_page(
            _db_path(),
            filter_=filter_,
            page=page,
            page_size=page_size,
        )
        return jsonify(
            {
                "positions": [p.model_dump() for p in result.positions],
                "page": {
                    "page": result.page.page,
                    "page_size": result.page.page_size,
                    "total": result.page.total,
                    "total_pages": result.page.total_pages,
                    "has_next": result.page.has_next,
                    "has_prev": result.page.has_prev,
                },
            }
        )

    @bp.get("/api/positions/filters")
    def filters_endpoint():
        return jsonify(get_filter_options(_db_path()))

    @bp.get("/api/positions/<account>/<instrument>/<entry_execution_id>")
    def get_endpoint(account: str, instrument: str, entry_execution_id: str):
        p = get_position(
            _db_path(),
            account=account,
            instrument=instrument,
            entry_execution_id=entry_execution_id,
        )
        if p is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(attach_metadata(_db_path(), p))

    @bp.get("/api/positions/<account>/<instrument>/<entry_execution_id>/executions")
    def get_executions(account: str, instrument: str, entry_execution_id: str):
        pf = get_position_with_fills(
            _db_path(),
            account=account,
            instrument=instrument,
            entry_execution_id=entry_execution_id,
        )
        if pf is None:
            return jsonify({"error": "not found"}), 404
        p, fills = pf
        # Rows come from the walk's Fill list, not raw executions: reversal
        # executions appear as #close/#open halves with split quantity, and
        # exit classification is by side — NT's CSV Entry/Exit label can be
        # wrong when its own position tracking has drifted.
        entry_side = "Buy" if p.side == "Long" else "Sell"
        sign = 1 if p.side == "Long" else -1
        multiplier = get_multiplier(p.instrument)
        parents = {ex.nt_execution_id: ex for ex in _position_executions(_db_path(), p)}
        executions = []
        for f in fills:
            e = parents[strip_split_suffix(f.execution_id)].model_dump()
            e["nt_execution_id"] = f.execution_id
            e["timestamp"] = f.timestamp
            e["side"] = f.side
            e["quantity"] = f.quantity
            e["price"] = f.price
            e["commission"] = f.commission
            if f.side == entry_side:
                e["entry_exit"] = "Entry"
                e["avg_entry_price"] = None
                e["pnl_points"] = None
                e["pnl_dollars_net"] = None
            else:
                e["entry_exit"] = "Exit"
                eff_comm = effective_commission(p.instrument, f.commission, f.quantity)
                pnl_points = (f.price - p.entry_price) * f.quantity * sign
                e["avg_entry_price"] = p.entry_price
                e["pnl_points"] = round(pnl_points, 4)
                e["pnl_dollars_net"] = round(pnl_points * multiplier - eff_comm, 2)
            executions.append(e)
        return jsonify({"executions": executions})

    @bp.get("/api/positions/<account>/<instrument>/<entry_execution_id>/markers")
    def get_markers(account: str, instrument: str, entry_execution_id: str):
        p = get_position(
            _db_path(),
            account=account,
            instrument=instrument,
            entry_execution_id=entry_execution_id,
        )
        if p is None:
            return jsonify({"error": "not found"}), 404
        markers = build_markers(_position_executions(_db_path(), p))
        return jsonify({"markers": [m.model_dump() for m in markers]})

    @bp.get("/api/integrity-issues")
    def list_integrity():
        status = request.args.get("status", "open")  # open|resolved|ignored|all
        severity = request.args.get("severity")
        accounts = [a for a in request.args.getlist("account") if a]
        instrument = request.args.get("instrument")

        clauses: list[str] = []
        params: list = []

        if status == "open":
            clauses.append("resolved_at IS NULL AND ignored = 0")
        elif status == "resolved":
            clauses.append("resolved_at IS NOT NULL")
        elif status == "ignored":
            clauses.append("ignored = 1")
        # status == "all": no clause

        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if accounts:
            placeholders = sql_placeholders(len(accounts))
            clauses.append(f"account IN ({placeholders})")
            params.extend(accounts)
        if instrument:
            clauses.append("instrument = ?")
            params.append(instrument)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM integrity_issues {where} "
            "ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,"
            " detected_at DESC LIMIT 500"
        )
        with read_conn(_db_path()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return jsonify({"issues": [dict(r) for r in rows]})

    @bp.post("/api/integrity-issues/<int:issue_id>/resolve")
    def resolve_integrity(issue_id: int):
        body = request.get_json(silent=True) or {}
        note = body.get("note")
        if note is not None and not isinstance(note, str):
            return jsonify({"error": "note must be a string"}), 400
        with transaction(_db_path()) as conn:
            mark_resolved_by_user(
                conn,
                issue_id=issue_id,
                now=int(time.time()),
                note=note,
            )
        return jsonify({"ok": True})

    @bp.post("/api/integrity-issues/<int:issue_id>/ignore")
    def ignore_integrity(issue_id: int):
        body = request.get_json(silent=True) or {}
        note = body.get("note")
        if not isinstance(note, str) or not note:
            return jsonify({"error": "note is required"}), 400
        with transaction(_db_path()) as conn:
            mark_ignored(conn, issue_id=issue_id, note=note)
        return jsonify({"ok": True})

    return bp
