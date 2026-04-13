import time
from pathlib import Path

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


def test_post_tick_hooks_include_integrity_and_ohlc(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        pipeline = app.config["FTL_IMPORT_PIPELINE"]
        # Plan 11 contributed the integrity hook; plan 14 appends the ohlc one.
        # We can't introspect by name (they're closures), but we can assert
        # the count and that submitting a tick triggers a fetch job.
        assert len(pipeline.post_tick_hooks) >= 2
    finally:
        services.stop()


def test_scheduled_refresh_jobs_registered(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        ids = {job.id for job in services.scheduler.get_jobs()}
        assert "ohlc_refresh_recent" in ids
        assert "ohlc_refresh_week" in ids
    finally:
        services.stop()


def test_ingest_tick_submits_ohlc_jobs_to_pool(tmp_config):
    """End-to-end: dropping a CSV causes the OHLC hook to enqueue jobs.

    We can't reach the real internet from the test, so we monkeypatch
    fetch_range to record its calls. The fixture starts background
    services so the watchdog actually fires.
    """
    calls: list[dict] = []

    def fake_fetch_range(*, db_path, registry, instrument, timeframe, start, end):
        calls.append({"instrument": instrument, "timeframe": timeframe})
        from models.bar import FetchResult

        return FetchResult(status="ok", bars_added=0, attempts=[])

    # NOTE: must patch BEFORE create_app reads the symbol if it does so at
    # module load time. The current implementation imports fetch_range
    # inside the hook closure, so patching here is sufficient.
    import services.ohlc.fetcher

    orig = services.ohlc.fetcher.fetch_range
    services.ohlc.fetcher.fetch_range = fake_fetch_range
    try:
        app, services_obj = create_app(tmp_config, start_background=True)
        try:
            header = (
                "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
                "Commission,Rate,Account,Connection,TradeValidation\n"
            )
            row = (
                "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,ohlctick1,Entry,1 L,"
                "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
            )
            path = Path(tmp_config.inbox_dir) / "NinjaTrader_Executions_20260413.csv"
            path.write_text(header + row, encoding="utf-8")

            deadline = time.time() + 3.0
            while time.time() < deadline and not calls:
                time.sleep(0.05)
            services_obj.pool.shutdown(wait=True)
            assert calls, "OHLC hook did not submit any fetch jobs"
            assert all(c["instrument"] == "MNQ" for c in calls)
        finally:
            services_obj.stop()
    finally:
        services.ohlc.fetcher.fetch_range = orig
