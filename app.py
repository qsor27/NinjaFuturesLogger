from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask

from background import BackgroundServices
from config import Config
from db import connect
from logging_config import configure_logging, get_logger
from migrations import run_migrations
from routes import health as health_routes
from routes.imports import build_imports_blueprint
from services.import_pipeline import ImportPipeline
from services.import_watchdog import TickHandler
from services.integrity import run_integrity_diff
from services.time_utils import resolve_current_trade_date

log = get_logger("http")

SAFETY_SWEEP_SECONDS = 300


def create_app(
    config: Config,
    *,
    start_background: bool = False,
) -> tuple[Flask, BackgroundServices]:
    """Build the Flask app and its BackgroundServices container."""
    configure_logging(level="INFO")

    conn = connect(config.db_path)
    try:
        run_migrations(conn, Path("migrations"))
    finally:
        conn.close()

    services = BackgroundServices(config)
    trader_tz = ZoneInfo(config.session.exchange_timezone)

    def _integrity_hook(_result, _parsed, affected):
        for acct, inst in affected:
            try:
                run_integrity_diff(config.db_path, acct, inst)
            except Exception:
                log.exception(
                    "integrity diff failed",
                    extra={"acct": acct, "inst": inst},
                )

    pipeline = ImportPipeline(
        db_path=config.db_path,
        trader_tz=trader_tz,
        post_tick_hooks=[_integrity_hook],
    )

    app = Flask(__name__)
    app.config["BACKGROUND_SERVICES"] = services
    app.config["DB_PATH"] = config.db_path
    app.config["HEARTBEAT_SECONDS"] = config.scheduler.heartbeat_seconds
    app.config["FTL_CONFIG"] = config
    app.config["FTL_DB_PATH"] = config.db_path
    app.config["FTL_INBOX_DIR"] = config.inbox_dir
    app.config["FTL_IMPORT_PIPELINE"] = pipeline

    app.register_blueprint(health_routes.bp)
    app.register_blueprint(build_imports_blueprint())

    services.scheduler.add_job(
        lambda: pipeline.scan_inbox(config.inbox_dir),
        trigger=IntervalTrigger(seconds=SAFETY_SWEEP_SECONDS),
        id="import_safety_sweep",
        replace_existing=True,
    )

    hour, minute = _parse_hhmm(config.session.archive_job_time)
    services.scheduler.add_job(
        lambda: _run_archival(pipeline, config, trader_tz),
        trigger=CronTrigger(hour=hour, minute=minute, timezone=trader_tz),
        id="archive_completed_sessions",
        replace_existing=True,
    )

    if start_background:
        services.start(handler=TickHandler(pipeline))

    log.info("app created", extra={"start_background": start_background})
    return app, services


def _parse_hhmm(value: str) -> tuple[int, int]:
    hh, mm = value.split(":")
    return int(hh), int(mm)


def _run_archival(pipeline: ImportPipeline, config: Config, trader_tz: ZoneInfo) -> None:
    now_local = datetime.now(trader_tz)
    today = resolve_current_trade_date(now_local)
    pipeline.archive_completed_sessions(
        inbox_dir=config.inbox_dir,
        archive_dir=config.archive_dir,
        current_trade_date=today,
    )
