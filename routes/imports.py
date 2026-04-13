from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger

log = get_logger("http.imports")


def build_imports_blueprint() -> Blueprint:
    bp = Blueprint("imports", __name__)

    def _db():
        return connect(current_app.config["FTL_DB_PATH"])

    def _pipeline():
        return current_app.config["FTL_IMPORT_PIPELINE"]

    @bp.get("/api/imports/runs")
    def list_runs():
        limit = min(int(request.args.get("limit", "100")), 500)
        offset = max(int(request.args.get("offset", "0")), 0)
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT tick_id, filename, started_at, finished_at, cursor_before,"
                " cursor_after, lines_read, rows_parsed, rows_inserted,"
                " rows_skipped_duplicate, rows_rejected, status, error "
                "FROM import_runs ORDER BY tick_id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        finally:
            conn.close()
        return jsonify({"runs": [dict(r) for r in rows]})

    @bp.get("/api/imports/runs/<int:tick_id>")
    def get_run(tick_id: int):
        conn = _db()
        try:
            row = conn.execute(
                "SELECT * FROM import_runs WHERE tick_id = ?", (tick_id,)
            ).fetchone()
            if row is None:
                return jsonify({"error": "not found"}), 404
            rejects = conn.execute(
                "SELECT reject_id, line_number, raw_line, reason, created_at "
                "FROM import_rejects WHERE tick_id = ? ORDER BY reject_id",
                (tick_id,),
            ).fetchall()
        finally:
            conn.close()
        body = dict(row)
        body["rejects"] = [dict(r) for r in rejects]
        return jsonify(body)

    @bp.get("/api/imports/cursors")
    def list_cursors():
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT filename, byte_offset, last_tick_at, last_modified "
                "FROM import_cursors ORDER BY filename"
            ).fetchall()
        finally:
            conn.close()
        return jsonify({"cursors": [dict(r) for r in rows]})

    @bp.post("/api/imports/scan")
    def scan():
        pipeline = _pipeline()
        inbox = current_app.config["FTL_INBOX_DIR"]
        results = pipeline.scan_inbox(inbox)
        return jsonify({
            "ticked": len(results),
            "results": [r.model_dump() for r in results],
        })

    @bp.get("/api/imports/rejects")
    def list_rejects():
        limit = min(int(request.args.get("limit", "100")), 500)
        offset = max(int(request.args.get("offset", "0")), 0)
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT reject_id, tick_id, line_number, raw_line, reason, created_at "
                "FROM import_rejects ORDER BY reject_id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        finally:
            conn.close()
        return jsonify({"rejects": [dict(r) for r in rows]})

    @bp.post("/api/executions/rollback")
    def rollback():
        body = request.get_json(silent=True) or {}
        ids = body.get("execution_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            return jsonify({"error": "execution_ids must be a non-empty list of strings"}), 400
        deleted = _pipeline().rollback(ids)
        return jsonify({"deleted": deleted})

    return bp
