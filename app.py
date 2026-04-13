from pathlib import Path

from flask import Flask

from background import BackgroundServices
from config import Config
from db import connect
from logging_config import configure_logging, get_logger
from migrations import run_migrations
from routes import health as health_routes

log = get_logger("http")


def create_app(
    config: Config,
    *,
    start_background: bool = False,
) -> tuple[Flask, BackgroundServices]:
    """Build the Flask app and its BackgroundServices container.

    Doc 03: returns a (Flask, BackgroundServices) tuple. Tests construct
    with start_background=False; production WSGI startup passes True.
    """
    configure_logging(level="INFO")

    # Apply schema migrations before anything else binds to the DB.
    conn = connect(config.db_path)
    try:
        run_migrations(conn, Path("migrations"))
    finally:
        conn.close()

    services = BackgroundServices(config)

    app = Flask(__name__)
    app.config["BACKGROUND_SERVICES"] = services
    app.config["DB_PATH"] = config.db_path
    app.config["HEARTBEAT_SECONDS"] = config.scheduler.heartbeat_seconds
    app.config["FTL_CONFIG"] = config

    app.register_blueprint(health_routes.bp)

    if start_background:
        services.start()

    log.info("app created", extra={"start_background": start_background})
    return app, services
