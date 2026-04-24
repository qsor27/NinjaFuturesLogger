"""First-run wizard: HTML page + JSON API for NT setup.

Surfaces:
  GET  /first-run                          - wizard HTML (vanilla JS)
  GET  /api/first-run/detect-nt            - Task 6
  POST /api/first-run/install-indicator    - Task 7
  GET  /api/first-run/inbox-status         - Task 8
  POST /api/first-run/complete             - Task 9
"""

from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from services.nt_detection import detect_ninjatrader


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

    return bp
