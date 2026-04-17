import time

from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger
from services.instruments import effective_commission, get_multiplier
from services.integrity_db import mark_ignored, mark_resolved_by_user
from services.markers import build_markers
from services.position_filters import PositionFilter
from services.positions_service import (
    attach_metadata,
    get_filter_options,
    get_position,
    list_positions_page,
)

log = get_logger("http.positions")


def _parse_filter_from_query(args) -> PositionFilter:
    from datetime import date
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    account = args.get("account") or None
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

    session_date = _date_or_none("session_date")
    session_date_from = _date_or_none("session_date_from")
    session_date_to = _date_or_none("session_date_to")

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
        account=account,
        instrument=instrument,
        side=side,
        outcome=outcome,
        entry_time_min=_int_or_none("entry_time_min"),
        entry_time_max=_int_or_none("entry_time_max"),
        session_date=session_date,
        session_date_from=session_date_from,
        session_date_to=session_date_to,
        day_of_week=day_of_week,
        hour_of_day=hour_of_day,
        hour_tz=hour_tz,
        trades_per_day=trades_per_day,
    )


def build_positions_blueprint() -> Blueprint:
    bp = Blueprint("positions", __name__)

    def _db_path():
        return current_app.config["FTL_DB_PATH"]

    @bp.get("/api/positions")
    def list_endpoint():
        try:
            filter_ = _parse_filter_from_query(request.args)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        try:
            page = int(request.args.get("page", "1"))
            page_size = int(request.args.get("page_size", "50"))
        except ValueError:
            return jsonify({"error": "page and page_size must be integers"}), 400
        page_size = max(1, min(page_size, 500))
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
        p = get_position(
            _db_path(),
            account=account,
            instrument=instrument,
            entry_execution_id=entry_execution_id,
        )
        if p is None:
            return jsonify({"error": "not found"}), 404
        # Load the raw executions for the (account, instrument) pair and
        # return only the ones whose nt_execution_id (with split suffix
        # stripped) appears in p.execution_ids.
        from services.notes import strip_split_suffix

        wanted = {strip_split_suffix(eid) for eid in p.execution_ids}
        conn = connect(_db_path())
        try:
            rows = conn.execute(
                "SELECT nt_execution_id, account, instrument, timestamp, side,"
                " original_action, quantity, price, commission, entry_exit,"
                " position_after, source_order_id, source_filename, imported_at "
                "FROM executions WHERE account = ? AND instrument = ? "
                "ORDER BY timestamp, nt_execution_id",
                (account, instrument),
            ).fetchall()
        finally:
            conn.close()
        sign = 1 if p.side == "Long" else -1
        multiplier = get_multiplier(p.instrument)
        executions = []
        for r in rows:
            if r["nt_execution_id"] not in wanted:
                continue
            e = dict(r)
            if e["entry_exit"] == "Exit":
                eff_comm = effective_commission(p.instrument, e["commission"], e["quantity"])
                pnl_points = (e["price"] - p.entry_price) * e["quantity"] * sign
                e["avg_entry_price"] = p.entry_price
                e["pnl_points"] = round(pnl_points, 4)
                e["pnl_dollars_net"] = round(pnl_points * multiplier - eff_comm, 2)
            else:
                e["avg_entry_price"] = None
                e["pnl_points"] = None
                e["pnl_dollars_net"] = None
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

        # Same lookup pattern as get_executions: load all (account, instrument)
        # executions, filter to the ones whose un-suffixed nt_execution_id
        # appears in the position's execution_ids, then build markers from
        # those real rows.
        from services.notes import strip_split_suffix

        wanted = {strip_split_suffix(eid) for eid in p.execution_ids}
        conn = connect(_db_path())
        try:
            rows = conn.execute(
                "SELECT nt_execution_id, account, instrument, timestamp, side,"
                " original_action, quantity, price, commission, entry_exit,"
                " position_after, source_order_id, source_filename, imported_at "
                "FROM executions WHERE account = ? AND instrument = ? "
                "ORDER BY timestamp, nt_execution_id",
                (account, instrument),
            ).fetchall()
        finally:
            conn.close()

        from models.execution import Execution

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
            if r["nt_execution_id"] in wanted
        ]
        markers = build_markers(executions)
        return jsonify({"markers": [m.model_dump() for m in markers]})

    @bp.get("/api/integrity-issues")
    def list_integrity():
        status = request.args.get("status", "open")  # open|resolved|ignored|all
        severity = request.args.get("severity")
        account = request.args.get("account")
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
        if account:
            clauses.append("account = ?")
            params.append(account)
        if instrument:
            clauses.append("instrument = ?")
            params.append(instrument)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM integrity_issues {where} "
            "ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,"
            " detected_at DESC LIMIT 500"
        )
        conn = connect(_db_path())
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return jsonify({"issues": [dict(r) for r in rows]})

    @bp.post("/api/integrity-issues/<int:issue_id>/resolve")
    def resolve_integrity(issue_id: int):
        body = request.get_json(silent=True) or {}
        note = body.get("note")
        if note is not None and not isinstance(note, str):
            return jsonify({"error": "note must be a string"}), 400
        conn = connect(_db_path())
        try:
            conn.execute("BEGIN")
            try:
                mark_resolved_by_user(
                    conn,
                    issue_id=issue_id,
                    now=int(time.time()),
                    note=note,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return jsonify({"ok": True})

    @bp.post("/api/integrity-issues/<int:issue_id>/ignore")
    def ignore_integrity(issue_id: int):
        body = request.get_json(silent=True) or {}
        note = body.get("note")
        if not isinstance(note, str) or not note:
            return jsonify({"error": "note is required"}), 400
        conn = connect(_db_path())
        try:
            conn.execute("BEGIN")
            try:
                mark_ignored(conn, issue_id=issue_id, note=note)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return jsonify({"ok": True})

    return bp
