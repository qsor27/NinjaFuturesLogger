"""Settings -> NT Connection panel data."""

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from services.nt_detection import detect_ninjatrader
from services.preferences import get_preference


def build_nt_connection_blueprint() -> Blueprint:
    bp = Blueprint("nt_connection", __name__)

    @bp.get("/api/settings/nt-connection")
    def nt_connection_status():
        override_raw = request.args.get("documents")
        override = Path(override_raw) if override_raw else None
        if override is not None and not override.is_dir():
            return jsonify({"error": "documents override must be an existing directory"}), 400

        detect = detect_ninjatrader(documents_override=override)
        installed_at_raw = get_preference(
            current_app.config["FTL_DB_PATH"], "indicator_installed_at"
        )
        installed_at = int(installed_at_raw) if installed_at_raw else None

        inbox = Path(current_app.config["FTL_INBOX_DIR"])
        if inbox.is_dir():
            files = sorted(inbox.glob("NinjaTrader_Executions_*.csv"))
        else:
            files = []
        if files:
            latest = max(files, key=lambda p: p.stat().st_mtime)
            inbox_payload = {
                "files_count": len(files),
                "last_csv_name": latest.name,
                "last_csv_mtime": int(latest.stat().st_mtime),
            }
        else:
            inbox_payload = {"files_count": 0, "last_csv_name": None, "last_csv_mtime": None}

        return jsonify(
            {
                "nt_found": detect.found,
                "indicators_path": str(detect.indicators_path) if detect.indicators_path else None,
                "indicator_installed_at": installed_at,
                "inbox": inbox_payload,
            }
        )

    return bp
