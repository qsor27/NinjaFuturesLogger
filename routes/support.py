import time
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request

from logging_config import get_logger
from routes._params import BadParam, int_arg
from services.support_bundle import build_bundle
from services.version import get_version

log = get_logger("http.support")

MIN_DAYS = 1
MAX_DAYS = 180
DEFAULT_DAYS = 7


def build_support_blueprint() -> Blueprint:
    bp = Blueprint("support", __name__)

    @bp.get("/api/support/bundle")
    def support_bundle():
        try:
            days = int_arg(request.args, "days", default=DEFAULT_DAYS, lo=MIN_DAYS, hi=MAX_DAYS)
        except BadParam as e:
            return jsonify({"error": str(e)}), 400

        db_path = current_app.config["FTL_DB_PATH"]
        log_dir = Path(current_app.config["FTL_LOG_DIR"])
        config_dir = Path(current_app.config["FTL_CONFIG_PATH"]).parent

        services = current_app.config["BACKGROUND_SERVICES"]
        try:
            system_health = services.system_health_snapshot()
        except Exception:
            log.exception("system_health_snapshot failed during bundle build")
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
        log.info(
            "support_bundle_issued",
            extra={"days": days, "bytes": len(payload)},
        )
        filename = f"support-bundle-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))}.zip"
        return Response(
            payload,
            mimetype="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return bp
