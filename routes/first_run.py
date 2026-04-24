"""First-run wizard: HTML page + JSON API for NT setup.

Surfaces:
  GET  /first-run                          - wizard HTML (vanilla JS)
  GET  /api/first-run/detect-nt            - Task 6
  POST /api/first-run/install-indicator    - Task 7
  GET  /api/first-run/inbox-status         - Task 8
  POST /api/first-run/complete             - Task 9
"""

import os
import time
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request

from services.nt_detection import detect_ninjatrader
from services.nt_indicator_install import install_indicator
from services.preferences import set_preference

VALID_ON_CONFLICT = {"overwrite", "keep", "backup_replace"}


def _resolve_source() -> Path:
    override = os.environ.get("FTL_NT_INDICATOR_SOURCE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "ninjascript" / "ExecutionExporter.cs"


def build_first_run_blueprint() -> Blueprint:
    bp = Blueprint("first_run", __name__)

    @bp.get("/first-run")
    def first_run_page():
        return render_template("first_run.html")

    @bp.get("/api/first-run/detect-nt")
    def detect_nt():
        override_raw = request.args.get("documents")
        override = Path(override_raw) if override_raw else None
        # Guard: only allow override when the path exists - prevents callers
        # from probing the filesystem via arbitrary strings.
        if override is not None and not override.is_dir():
            return jsonify({"error": "documents override must be an existing directory"}), 400
        result = detect_ninjatrader(documents_override=override)
        return jsonify(
            {
                "found": result.found,
                "indicators_path": str(result.indicators_path) if result.indicators_path else None,
            }
        )

    @bp.post("/api/first-run/install-indicator")
    def install_indicator_route():
        body = request.get_json(silent=True) or {}
        dest_dir_raw = body.get("dest_dir")
        on_conflict = body.get("on_conflict")
        if not isinstance(dest_dir_raw, str) or not dest_dir_raw:
            return jsonify({"error": "dest_dir is required"}), 400
        if on_conflict not in VALID_ON_CONFLICT:
            return jsonify(
                {"error": f"on_conflict must be one of {sorted(VALID_ON_CONFLICT)}"}
            ), 400

        result = install_indicator(
            source=_resolve_source(),
            dest_dir=Path(dest_dir_raw),
            on_conflict=on_conflict,
        )
        if result.success:
            set_preference(
                current_app.config["FTL_DB_PATH"],
                "indicator_installed_at",
                str(int(time.time())),
            )
        return jsonify(
            {
                "success": result.success,
                "dest_path": str(result.dest_path) if result.dest_path else None,
                "backup_path": str(result.backup_path) if result.backup_path else None,
                "error": result.error,
            }
        )

    return bp
