import time

from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger
from services.integrity_db import mark_ignored, mark_resolved_by_user
from services.position_filters import PositionFilter
from services.positions_service import (
    attach_metadata,
    get_filter_options,
    get_position,
    list_positions_page,
)

log = get_logger("http.positions")


def _parse_filter_from_query(args) -> PositionFilter:
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

    return PositionFilter(
        account=account,
        instrument=instrument,
        side=side,
        outcome=outcome,
        entry_time_min=_int_or_none("entry_time_min"),
        entry_time_max=_int_or_none("entry_time_max"),
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
        return jsonify({
            "positions": [p.model_dump() for p in result.positions],
            "page": {
                "page": result.page.page,
                "page_size": result.page.page_size,
                "total": result.page.total,
                "total_pages": result.page.total_pages,
                "has_next": result.page.has_next,
                "has_prev": result.page.has_prev,
            },
        })

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
        filtered = [dict(r) for r in rows if r["nt_execution_id"] in wanted]
        return jsonify({"executions": filtered})

    @bp.get("/api/integrity-issues")
    def list_integrity():
        conn = connect(_db_path())
        try:
            rows = conn.execute(
                "SELECT * FROM integrity_issues "
                "WHERE resolved_at IS NULL AND ignored = 0 "
                "ORDER BY issue_id DESC LIMIT 500"
            ).fetchall()
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
