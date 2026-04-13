import time

from flask import Blueprint, current_app, jsonify

from db import connect

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    services = current_app.config["BACKGROUND_SERVICES"]
    db_path = current_app.config["DB_PATH"]
    heartbeat_seconds = current_app.config["HEARTBEAT_SECONDS"]

    sqlite_ok = False
    try:
        conn = connect(db_path)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        sqlite_ok = True
    except Exception:
        sqlite_ok = False

    scheduler_ok = services.scheduler_running()
    watchdog_ok = services.observer_alive()

    # `tick_fresh` is informational here; foundation does not gate on it.
    # Plan 17 hardens this once real scheduled jobs exist to keep the
    # heartbeat moving under load.
    last_tick = services.last_scheduler_tick()
    tick_fresh = (
        last_tick is not None
        and (int(time.time()) - last_tick) <= max(heartbeat_seconds * 2, 5)
    )
    pool_saturated = False  # plan 10+ submits real work; foundation reports false.

    body = {
        "sqlite": sqlite_ok,
        "scheduler": scheduler_ok,
        "watchdog": watchdog_ok,
        "pool_saturated": pool_saturated,
        "tick_fresh": tick_fresh,
    }
    healthy = sqlite_ok and scheduler_ok and watchdog_ok and not pool_saturated
    return jsonify(body), 200 if healthy else 503
