def test_plan19_registers_new_jobs_and_drops_old_ones(app_and_services):
    # Plan 19: old interval-based refresh jobs were replaced with the
    # coverage maintainer, historical sweep, and cron-based refreshes.
    app, services = app_and_services
    job_ids = {j.id for j in services.scheduler.get_jobs()}
    assert "ohlc_coverage_maintainer" in job_ids
    assert "ohlc_historical_sweep" in job_ids
    assert "ohlc_daily_refresh" in job_ids
    assert "ohlc_weekly_refresh" in job_ids
    assert "ohlc_monthly_refresh" in job_ids
    assert "ohlc_refresh_recent" not in job_ids
    assert "ohlc_refresh_week" not in job_ids


def test_plan19_drops_post_import_ohlc_hook(app_and_services):
    # Plan 19: the post-import OHLC hook was removed. Coverage maintenance
    # is driven entirely by scheduled jobs, so only the integrity hook
    # remains on the import pipeline.
    app, services = app_and_services
    pipeline = app.config["FTL_IMPORT_PIPELINE"]
    hook_names = [fn.__name__ for fn in pipeline.post_tick_hooks]
    assert "_ohlc_hook" not in hook_names
    assert "_integrity_hook" in hook_names


def test_plan19_token_bucket_stored_in_app_config(app_and_services):
    from services.ohlc.rate_limiter import TokenBucket

    app, services = app_and_services
    bucket = app.config["FTL_OHLC_TOKEN_BUCKET"]
    assert isinstance(bucket, TokenBucket)
    stats = bucket.stats()
    assert stats["capacity"] == 30
    assert stats["refill_per_sec"] == 0.5
