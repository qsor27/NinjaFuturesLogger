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
        limit = min(int(request.args.get("limit", "50")), 500)
        offset = max(int(request.args.get("offset", "0")), 0)
        start_ts = request.args.get("start_ts")
        end_ts = request.args.get("end_ts")
        filename = request.args.get("filename")
        status = request.args.get("status")

        clauses: list[str] = []
        params: list = []
        if start_ts is not None:
            clauses.append("started_at >= ?")
            params.append(int(start_ts))
        if end_ts is not None:
            clauses.append("started_at <= ?")
            params.append(int(end_ts))
        if filename:
            clauses.append("filename LIKE ?")
            params.append(f"%{filename}%")
        if status:
            clauses.append("status = ?")
            params.append(status)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT tick_id, filename, started_at, finished_at, cursor_before,"
            " cursor_after, lines_read, rows_parsed, rows_inserted,"
            " rows_skipped_duplicate, rows_rejected, status, error "
            f"FROM import_runs {where} ORDER BY tick_id DESC LIMIT ? OFFSET ?"
        )
        conn = _db()
        try:
            rows = conn.execute(sql, (*params, limit, offset)).fetchall()
            total = conn.execute(
                f"SELECT COUNT(*) FROM import_runs {where}", params
            ).fetchone()[0]
        finally:
            conn.close()
        return jsonify({"runs": [dict(r) for r in rows], "total": total})

    @bp.get("/api/imports/runs/<int:tick_id>")
    def get_run(tick_id: int):
        conn = _db()
        try:
            row = conn.execute("SELECT * FROM import_runs WHERE tick_id = ?", (tick_id,)).fetchone()
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

    @bp.get("/api/imports/runs/<int:tick_id>/executions")
    def get_run_executions(tick_id: int):
        conn = _db()
        try:
            run = conn.execute(
                "SELECT filename, started_at, finished_at FROM import_runs WHERE tick_id = ?",
                (tick_id,),
            ).fetchone()
            if run is None:
                return jsonify({"error": "not found"}), 404
            rows = conn.execute(
                "SELECT nt_execution_id FROM executions "
                "WHERE source_filename = ? AND imported_at BETWEEN ? AND ?",
                (run["filename"], run["started_at"], run["finished_at"] + 5),
            ).fetchall()
        finally:
            conn.close()
        return jsonify({"execution_ids": [r["nt_execution_id"] for r in rows]})

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
        return jsonify(
            {
                "ticked": len(results),
                "results": [r.model_dump() for r in results],
            }
        )

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
