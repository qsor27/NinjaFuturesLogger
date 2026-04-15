from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig
from app import create_app


def _make_config(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "logs").mkdir()
    return Config(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "t.db"),
        inbox_dir=str(tmp_path / "inbox"),
        archive_dir=str(tmp_path / "archive"),
        log_dir=str(tmp_path / "logs"),
        session=SessionConfig(
            exchange_timezone="America/Chicago",
            trade_date_rollover="16:00",
            archive_job_time="18:00",
        ),
        thread_pool=ThreadPoolConfig(max_workers=2),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
    )


def test_plan19_registers_new_jobs_and_drops_old_ones(tmp_path):
    cfg = _make_config(tmp_path)
    app, services = create_app(cfg, start_background=False)
    try:
        job_ids = {j.id for j in services.scheduler.get_jobs()}
    finally:
        services.stop()
    assert "ohlc_coverage_maintainer" in job_ids
    assert "ohlc_historical_sweep" in job_ids
    assert "ohlc_daily_refresh" in job_ids
    assert "ohlc_weekly_refresh" in job_ids
    assert "ohlc_monthly_refresh" in job_ids
    assert "ohlc_refresh_recent" not in job_ids
    assert "ohlc_refresh_week" not in job_ids


def test_plan19_drops_post_import_ohlc_hook(tmp_path):
    cfg = _make_config(tmp_path)
    app, services = create_app(cfg, start_background=False)
    try:
        pipeline = app.config["FTL_IMPORT_PIPELINE"]
        hook_names = [fn.__name__ for fn in pipeline.post_tick_hooks]
    finally:
        services.stop()
    assert "_ohlc_hook" not in hook_names
    assert "_integrity_hook" in hook_names


def test_plan19_token_bucket_stored_in_app_config(tmp_path):
    from services.ohlc.rate_limiter import TokenBucket
    cfg = _make_config(tmp_path)
    app, services = create_app(cfg, start_background=False)
    try:
        bucket = app.config["FTL_OHLC_TOKEN_BUCKET"]
        assert isinstance(bucket, TokenBucket)
        stats = bucket.stats()
        assert stats["capacity"] == 30
        assert stats["refill_per_sec"] == 0.5
    finally:
        services.stop()
