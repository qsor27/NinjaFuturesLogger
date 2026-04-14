import time

from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger
from services.flags import set_reviewed
from services.notes import strip_split_suffix, upsert_note

log = get_logger("http.user_metadata")


def build_user_metadata_blueprint() -> Blueprint:
    bp = Blueprint("user_metadata", __name__)

    def _db_path():
        return current_app.config["FTL_DB_PATH"]

    def _execution_exists(execution_id: str) -> bool:
        real_id = strip_split_suffix(execution_id)
        conn = connect(_db_path())
        try:
            row = conn.execute(
                "SELECT 1 FROM executions WHERE nt_execution_id = ?",
                (real_id,),
            ).fetchone()
        finally:
            conn.close()
        return row is not None

    @bp.patch("/api/executions/<execution_id>/note")
    def patch_note(execution_id: str):
        body = request.get_json(silent=True) or {}
        note = body.get("note")
        if not isinstance(note, str):
            return jsonify({"error": "note must be a string"}), 400
        if not _execution_exists(execution_id):
            return jsonify({"error": "execution not found"}), 404
        upsert_note(
            _db_path(),
            execution_id=execution_id,
            note=note,
            now=int(time.time()),
        )
        return jsonify({"ok": True})

    @bp.patch("/api/executions/<execution_id>/reviewed")
    def patch_reviewed(execution_id: str):
        body = request.get_json(silent=True) or {}
        reviewed = body.get("reviewed")
        if not isinstance(reviewed, bool):
            return jsonify({"error": "reviewed must be a boolean"}), 400
        if not _execution_exists(execution_id):
            return jsonify({"error": "execution not found"}), 404
        set_reviewed(
            _db_path(),
            execution_id=execution_id,
            reviewed=reviewed,
            now=int(time.time()),
        )
        return jsonify({"ok": True})

    return bp
