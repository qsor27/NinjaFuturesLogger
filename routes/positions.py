import time

from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger
from services.integrity_db import mark_ignored, mark_resolved_by_user
from services.positions_service import get_position, list_positions

log = get_logger("http.positions")


def build_positions_blueprint() -> Blueprint:
    bp = Blueprint("positions", __name__)

    def _db_path():
        return current_app.config["FTL_DB_PATH"]

    @bp.get("/api/positions")
    def list_endpoint():
        account = request.args.get("account")
        instrument = request.args.get("instrument")
        positions = list_positions(
            _db_path(),
            account=account,
            instrument=instrument,
        )
        return jsonify({"positions": [p.model_dump() for p in positions]})

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
        return jsonify(p.model_dump())

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
