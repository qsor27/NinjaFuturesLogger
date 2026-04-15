from app import create_app
from db import connect
from models.bar import Bar
from services.ohlc.store import insert_many


def test_ohlc_blueprint_registered_and_chart_endpoint_works(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        conn = connect(tmp_config.db_path)
        try:
            insert_many(
                conn,
                [
                    Bar(
                        instrument="MNQ",
                        timeframe="1d",
                        time=86400,
                        open=1,
                        high=2,
                        low=0.5,
                        close=1.5,
                        volume=10,
                        source="seed",
                    )
                ],
            )
        finally:
            conn.close()
        resp = app.test_client().get("/api/chart/MNQ?timeframe=1d&start=0&end=999999999")
        assert resp.status_code == 200
        assert len(resp.get_json()["bars"]) == 1
    finally:
        services.stop()


def test_sources_endpoint_lists_yfinance_and_stooq(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/ohlc/sources")
        assert resp.status_code == 200
        names = {s["name"] for s in resp.get_json()["sources"]}
        assert names == {"yfinance", "stooq"}
    finally:
        services.stop()


def test_post_tick_hooks_include_only_integrity(tmp_config):
    # Plan 19: the post-import OHLC hook was removed. Coverage maintenance
    # is driven entirely by scheduled jobs, so only the integrity hook
    # remains on the import pipeline.
    app, services = create_app(tmp_config, start_background=False)
    try:
        pipeline = app.config["FTL_IMPORT_PIPELINE"]
        hook_names = [fn.__name__ for fn in pipeline.post_tick_hooks]
        assert "_integrity_hook" in hook_names
        assert "_ohlc_hook" not in hook_names
    finally:
        services.stop()


def test_scheduled_refresh_jobs_registered(tmp_config):
    # Plan 19: old interval-based refresh jobs were replaced with the
    # coverage maintainer, historical sweep, and cron-based refreshes.
    app, services = create_app(tmp_config, start_background=False)
    try:
        ids = {job.id for job in services.scheduler.get_jobs()}
        assert "ohlc_coverage_maintainer" in ids
        assert "ohlc_historical_sweep" in ids
        assert "ohlc_daily_refresh" in ids
        assert "ohlc_weekly_refresh" in ids
        assert "ohlc_monthly_refresh" in ids
        assert "ohlc_refresh_recent" not in ids
        assert "ohlc_refresh_week" not in ids
    finally:
        services.stop()
