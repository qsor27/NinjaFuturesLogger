import time

from db import connect
from models.bar import Bar
from routes.ohlc import build_ohlc_blueprint
from services.ohlc.jobs import FetchJobRegistry
from services.ohlc.registry import build_default_registry
from services.ohlc.store import insert_many


def _seed_bar(db_path, t):
    conn = connect(db_path)
    try:
        insert_many(
            conn,
            [
                Bar(
                    instrument="MNQ",
                    timeframe="1d",
                    time=t,
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


def _make_app(tmp_config, *, jobs=None, registry=None, token_bucket=None):
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    from flask import Flask

    from migrations import run_migrations

    conn = connect(tmp_config.db_path)
    try:
        run_migrations(conn, Path("migrations"))
    finally:
        conn.close()

    pool = ThreadPoolExecutor(max_workers=2)
    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = tmp_config.db_path
    app.config["FTL_OHLC_POOL"] = pool
    app.config["FTL_OHLC_JOBS"] = jobs or FetchJobRegistry()
    app.config["FTL_OHLC_REGISTRY"] = registry or build_default_registry(
        clock=lambda: int(time.time())
    )
    if token_bucket is not None:
        app.config["FTL_OHLC_TOKEN_BUCKET"] = token_bucket
    app.register_blueprint(build_ohlc_blueprint())
    return app, pool


def test_get_chart_reads_only(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        _seed_bar(tmp_config.db_path, 86400)
        resp = app.test_client().get("/api/chart/MNQ?timeframe=1d&start=0&end=999999999")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["instrument"] == "MNQ"
        assert body["timeframe"] == "1d"
        assert len(body["bars"]) == 1
        assert body["bars"][0]["close"] == 1.5
    finally:
        pool.shutdown(wait=True)


def test_get_chart_empty_window_returns_empty(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().get("/api/chart/MNQ?timeframe=1d&start=0&end=10")
        assert resp.status_code == 200
        assert resp.get_json()["bars"] == []
    finally:
        pool.shutdown(wait=True)


def test_get_chart_rejects_unknown_timeframe(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().get("/api/chart/MNQ?timeframe=2m&start=0&end=10")
        assert resp.status_code == 400
    finally:
        pool.shutdown(wait=True)


def test_post_chart_fetch_returns_job_id_immediately(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().post(
            "/api/chart/MNQ/fetch",
            json={"timeframe": "1d", "start": 86400, "end": 86400 * 3},
        )
        assert resp.status_code == 202
        body = resp.get_json()
        assert "job_id" in body
        assert isinstance(body["job_id"], str)
    finally:
        pool.shutdown(wait=True)


def test_get_job_status_unknown(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().get("/api/ohlc/jobs/notreal")
        assert resp.status_code == 404
    finally:
        pool.shutdown(wait=True)


def test_get_job_status_known(tmp_config):
    jobs = FetchJobRegistry()
    app, pool = _make_app(tmp_config, jobs=jobs)
    try:
        job_id = jobs.submit(pool, lambda: 1, meta={"instrument": "MNQ"})
        # Poll until the job lands
        for _ in range(200):
            if jobs.status(job_id)["state"] == "done":
                break
            time.sleep(0.01)
        resp = app.test_client().get(f"/api/ohlc/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["state"] == "done"
    finally:
        pool.shutdown(wait=True)


def test_get_sources_returns_per_source_breaker_state(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().get("/api/ohlc/sources")
        assert resp.status_code == 200
        body = resp.get_json()
        names = {s["name"] for s in body["sources"]}
        assert names == {"yfinance", "stooq"}
        for s in body["sources"]:
            assert s["state"] == "closed"
            # Plan 18: adaptive-breaker fields must be surfaced
            assert "consecutive_trips" in s
            assert "current_cooldown_seconds" in s
            assert "next_retry_at" in s
            assert "last_failure_class" in s
            assert s["consecutive_trips"] == 0
            assert s["next_retry_at"] is None
            assert s["last_failure_class"] is None
    finally:
        pool.shutdown(wait=True)


def test_post_chart_fetch_acquires_from_token_bucket(tmp_config):
    """B7: on-demand fetches must go through the global token bucket."""
    from services.ohlc.rate_limiter import TokenBucket
    from services.ohlc.registry import SourceRegistry

    class _Source:
        name = "fake"
        supported_timeframes = frozenset({"1d"})

        def fetch(self, instrument, timeframe, start, end):
            return []

    reg = SourceRegistry(clock=lambda: int(time.time()))
    reg.register(_Source(), failure_threshold=3, base_cooldown_seconds=60)
    bucket = TokenBucket(capacity=5, refill_per_sec=0.0, clock=time.monotonic)
    jobs = FetchJobRegistry()
    app, pool = _make_app(tmp_config, jobs=jobs, registry=reg, token_bucket=bucket)
    try:
        resp = app.test_client().post(
            "/api/chart/MNQ/fetch",
            json={"timeframe": "1d", "start": 86400, "end": 86400 * 3},
        )
        assert resp.status_code == 202
        job_id = resp.get_json()["job_id"]
        for _ in range(500):
            if jobs.status(job_id)["state"] != "pending":
                break
            time.sleep(0.01)
        assert jobs.status(job_id)["state"] == "done"
        assert bucket.stats()["acquired_total"] >= 1
    finally:
        pool.shutdown(wait=True)
