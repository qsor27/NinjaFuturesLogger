import time
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request

from services.support_bundle import build_bundle
from services.version import get_version

MIN_DAYS = 1
MAX_DAYS = 180
DEFAULT_DAYS = 7


def build_support_blueprint() -> Blueprint:
    bp = Blueprint("support", __name__)

    @bp.get("/api/support/bundle")
    def support_bundle():
        raw_days = request.args.get("days", str(DEFAULT_DAYS))
        try:
            days = int(raw_days)
        except ValueError:
            return jsonify({"error": f"days must be an integer, got {raw_days!r}"}), 400
        if days < MIN_DAYS or days > MAX_DAYS:
            return jsonify({"error": f"days must be in [{MIN_DAYS}, {MAX_DAYS}]"}), 400

        db_path = current_app.config["FTL_DB_PATH"]
        log_dir = Path(current_app.config["FTL_LOG_DIR"])
        config_dir = Path(current_app.config["FTL_CONFIG_PATH"]).parent

        services = current_app.config["BACKGROUND_SERVICES"]
        try:
            system_health = services.system_health_snapshot()
        except Exception:
            system_health = {"error": "system_health_snapshot raised"}

        now = int(time.time())
        payload = build_bundle(
            db_path=db_path,
            log_dir=log_dir,
            config_dir=config_dir,
            version=get_version(),
            days=days,
            now=now,
            system_health=system_health,
        )
        filename = f"support-bundle-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))}.zip"
        return Response(
            payload,
            mimetype="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return bp
