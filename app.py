import calendar
import time as _time
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
from migrations_python import apply_json_migrations
from routes import health as health_routes
from routes.filter_defaults import build_filter_defaults_blueprint
from routes.imports import build_imports_blueprint
from routes.monitoring import build_monitoring_blueprint
from routes.ohlc import build_ohlc_blueprint
from routes.pages import build_pages_blueprint
from routes.positions import build_positions_blueprint
from routes.settings import build_settings_blueprint
from routes.stats import build_stats_blueprint
from routes.support import build_support_blueprint
from routes.user_metadata import build_user_metadata_blueprint
from services.import_pipeline import ImportPipeline
from services.import_watchdog import TickHandler
from services.integrity import run_integrity_diff
from services.ohlc.coverage_maintainer import (
    coverage_maintainer_tick,
    historical_sweep_tick,
)
from services.ohlc.coverage_state import list_coverage, refresh_instrument_coverage_state
from services.ohlc.jobs import FetchJobRegistry
from services.ohlc.rate_limiter import TokenBucket
from services.ohlc.registry import build_default_registry
from services.time_utils import resolve_current_trade_date

log = get_logger("http")

SAFETY_SWEEP_SECONDS = 300


def create_app(
    config: Config,
    *,
    start_background: bool = False,
) -> tuple[Flask, BackgroundServices]:
    """Build the Flask app and its BackgroundServices container."""
    log_file = Path(config.log_dir) / "app.jsonl"
    configure_logging(level="INFO", log_file=log_file)

    conn = connect(config.db_path)
    try:
        run_migrations(conn, Path("migrations"))
        from services.ohlc.attempts import orphan_sweep

        orphan_sweep(conn, now=int(_time.time()))
        conn.commit()
    finally:
        conn.close()

    apply_json_migrations(Path(config.data_dir) / "config" / "instruments.json")

    from services.instruments import get_registry, set_registry_path

    set_registry_path(Path(config.data_dir) / "config" / "instruments.json")
    get_registry().load()

    services = BackgroundServices(config)
    trader_tz = ZoneInfo(config.session.source_timezone or config.session.exchange_timezone)

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

    ohlc_registry = build_default_registry(clock=lambda: int(_time.time()), db_path=config.db_path)
    ohlc_jobs = FetchJobRegistry()

    token_bucket = TokenBucket(capacity=30, refill_per_sec=0.5, clock=_time.monotonic)

    def _fetch(*, db_path, instrument, timeframe, start, end, trigger):
        from services.ohlc.fetcher import fetch_range  # deferred to allow tests to monkeypatch

        fetch_range(
            db_path=db_path,
            registry=ohlc_registry,
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
            trigger=trigger,
            token_bucket=token_bucket,
        )

    app = Flask(__name__)
    app.config["BACKGROUND_SERVICES"] = services
    app.config["DB_PATH"] = config.db_path
    app.config["HEARTBEAT_SECONDS"] = config.scheduler.heartbeat_seconds
    app.config["FTL_CONFIG"] = config
    app.config["FTL_CONFIG_PATH"] = str(Path(config.data_dir) / "config" / "app.json")
    app.config["FTL_LOG_DIR"] = config.log_dir
    app.config["FTL_DB_PATH"] = config.db_path
    app.config["FTL_INBOX_DIR"] = config.inbox_dir
    app.config["FTL_IMPORT_PIPELINE"] = pipeline
    app.config["FTL_OHLC_REGISTRY"] = ohlc_registry
    app.config["FTL_OHLC_JOBS"] = ohlc_jobs
    app.config["FTL_OHLC_POOL"] = services.pool
    app.config["FTL_OHLC_TOKEN_BUCKET"] = token_bucket

    @app.context_processor
    def _inject_template_globals() -> dict[str, str]:
        cfg: Config = app.config["FTL_CONFIG"]
        # Empty string = use the browser's local tz. A non-empty value overrides.
        return {
            "display_tz": cfg.display_timezone or "",
            "theme": cfg.theme,
        }

    app.register_blueprint(health_routes.bp)
    app.register_blueprint(build_imports_blueprint())
    app.register_blueprint(build_positions_blueprint())
    app.register_blueprint(build_ohlc_blueprint())
    app.register_blueprint(build_user_metadata_blueprint())
    app.register_blueprint(build_settings_blueprint())
    app.register_blueprint(build_pages_blueprint())
    app.register_blueprint(build_stats_blueprint())
    app.register_blueprint(build_monitoring_blueprint())
    app.register_blueprint(build_filter_defaults_blueprint())
    app.register_blueprint(build_support_blueprint())

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

    services.scheduler.add_job(
        lambda: coverage_maintainer_tick(
            db_path=config.db_path, fetch_fn=_fetch, now=int(_time.time())
        ),
        trigger=IntervalTrigger(minutes=30),
        id="ohlc_coverage_maintainer",
        replace_existing=True,
    )
    services.scheduler.add_job(
        lambda: historical_sweep_tick(
            db_path=config.db_path, fetch_fn=_fetch, now=int(_time.time())
        ),
        trigger=IntervalTrigger(hours=4),
        id="ohlc_historical_sweep",
        replace_existing=True,
    )

    from services.ohlc.self_heal import self_heal_tick

    services.scheduler.add_job(
        lambda: self_heal_tick(db_path=config.db_path, fetch_fn=_fetch, now=int(_time.time())),
        trigger=IntervalTrigger(minutes=15),
        id="ohlc_self_heal",
        replace_existing=True,
    )

    from services.ohlc.attempts import trim_older_than

    def _retention_trim():
        cutoff = int(_time.time()) - 30 * 86400
        conn = connect(config.db_path)
        try:
            conn.execute("BEGIN")
            trim_older_than(conn, cutoff=cutoff)
            conn.execute("COMMIT")
        finally:
            conn.close()

    services.scheduler.add_job(
        _retention_trim,
        trigger=CronTrigger(hour=3, minute=0, timezone="America/Chicago"),
        id="ohlc_attempts_retention",
        replace_existing=True,
    )

    def _fetch_tf_for_active(tf: str, *, window_seconds: int) -> None:
        conn = connect(config.db_path)
        try:
            now = int(_time.time())
            refresh_instrument_coverage_state(conn, now=now)
            rows = [r for r in list_coverage(conn) if r.state == "active"]
        finally:
            conn.close()
        end = int(_time.time())
        start = end - window_seconds
        for row in rows:
            try:
                _fetch(
                    db_path=config.db_path,
                    instrument=row.instrument,
                    timeframe=tf,
                    start=start,
                    end=end,
                    trigger="sweep",
                )
            except Exception:
                log.exception(
                    "scheduled refresh failed",
                    extra={"instrument": row.instrument, "tf": tf},
                )

    services.scheduler.add_job(
        lambda: _fetch_tf_for_active("1d", window_seconds=10 * 365 * 86400),
        trigger=CronTrigger(hour=16, minute=1, timezone="America/Chicago"),
        id="ohlc_daily_refresh",
        replace_existing=True,
    )
    services.scheduler.add_job(
        lambda: _fetch_tf_for_active("1wk", window_seconds=10 * 365 * 86400),
        trigger=CronTrigger(day_of_week="fri", hour=16, minute=1, timezone="America/Chicago"),
        id="ohlc_weekly_refresh",
        replace_existing=True,
    )

    def _run_monthly():
        _fetch_tf_for_active("1mo", window_seconds=40 * 365 * 86400)
        _schedule_next_monthly()

    def _schedule_next_monthly():
        tz = ZoneInfo("America/Chicago")
        now_local = datetime.now(tz)
        last_day = calendar.monthrange(now_local.year, now_local.month)[1]
        run_date = now_local.replace(day=last_day, hour=16, minute=1, second=0, microsecond=0)
        if run_date <= now_local:
            m = now_local.month + 1
            y = now_local.year + (1 if m > 12 else 0)
            m = ((m - 1) % 12) + 1
            last_day = calendar.monthrange(y, m)[1]
            run_date = run_date.replace(year=y, month=m, day=last_day)
        services.scheduler.add_job(
            _run_monthly,
            trigger="date",
            run_date=run_date,
            id="ohlc_monthly_refresh",
            replace_existing=True,
        )

    _schedule_next_monthly()

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
