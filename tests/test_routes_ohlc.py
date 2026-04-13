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
        insert_many(conn, [Bar(
            instrument="MNQ", timeframe="1d", time=t,
            open=1, high=2, low=0.5, close=1.5, volume=10,
            source="seed",
        )])
    finally:
        conn.close()


def _make_app(tmp_config, *, jobs=None, registry=None):
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
    app.register_blueprint(build_ohlc_blueprint())
    return app, pool


def test_get_chart_reads_only(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        _seed_bar(tmp_config.db_path, 86400)
        resp = app.test_client().get(
            "/api/chart/MNQ?timeframe=1d&start=0&end=999999999"
        )
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
        resp = app.test_client().get(
            "/api/chart/MNQ?timeframe=1d&start=0&end=10"
        )
        assert resp.status_code == 200
        assert resp.get_json()["bars"] == []
    finally:
        pool.shutdown(wait=True)


def test_get_chart_rejects_unknown_timeframe(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().get(
            "/api/chart/MNQ?timeframe=2m&start=0&end=10"
        )
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
    finally:
        pool.shutdown(wait=True)
