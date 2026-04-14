import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask

from db import connect
from migrations import run_migrations
from models.bar import Bar
from routes.ohlc import build_ohlc_blueprint
from services.ohlc.jobs import FetchJobRegistry
from services.ohlc.registry import build_default_registry
from services.ohlc.store import insert_many


CANONICAL = ["1m", "5m", "15m", "1h", "4h", "1d"]


def _make_app(tmp_config):
    conn = connect(tmp_config.db_path)
    try:
        run_migrations(conn, Path("migrations"))
    finally:
        conn.close()

    pool = ThreadPoolExecutor(max_workers=2)
    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = tmp_config.db_path
    app.config["FTL_OHLC_POOL"] = pool
    app.config["FTL_OHLC_JOBS"] = FetchJobRegistry()
    app.config["FTL_OHLC_REGISTRY"] = build_default_registry(
        clock=lambda: int(time.time())
    )
    app.register_blueprint(build_ohlc_blueprint())
    return app, pool


def _seed(db_path, *, instrument, timeframe, time_, n=1):
    conn = connect(db_path)
    try:
        insert_many(
            conn,
            [
                Bar(
                    instrument=instrument,
                    timeframe=timeframe,
                    time=time_ + i,
                    open=1.0,
                    high=2.0,
                    low=0.5,
                    close=1.5,
                    volume=10,
                    source="seed",
                )
                for i in range(n)
            ],
        )
    finally:
        conn.close()


def test_empty_db_returns_all_canonical_timeframes_unavailable(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().get("/api/chart/MNQ/timeframes-available")
        assert resp.status_code == 200
        body = resp.get_json()
        assert [tf["timeframe"] for tf in body["timeframes"]] == CANONICAL
        assert all(tf["available"] is False for tf in body["timeframes"])
        assert all(tf["count"] == 0 for tf in body["timeframes"])
    finally:
        pool.shutdown(wait=True)


def test_default_timeframe_comes_from_chart_defaults(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        body = app.test_client().get("/api/chart/MNQ/timeframes-available").get_json()
        assert body["default_timeframe"] == "1m"
    finally:
        pool.shutdown(wait=True)


def test_partially_seeded_timeframes_report_count(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        _seed(tmp_config.db_path, instrument="MNQ", timeframe="1d", time_=86400, n=3)
        _seed(tmp_config.db_path, instrument="MNQ", timeframe="1m", time_=60, n=10)
        body = app.test_client().get("/api/chart/MNQ/timeframes-available").get_json()
        by_tf = {row["timeframe"]: row for row in body["timeframes"]}
        assert by_tf["1m"]["available"] is True
        assert by_tf["1m"]["count"] == 10
        assert by_tf["1d"]["available"] is True
        assert by_tf["1d"]["count"] == 3
        assert by_tf["5m"]["available"] is False
        assert by_tf["5m"]["count"] == 0
    finally:
        pool.shutdown(wait=True)


def test_canonical_order_is_stable(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        _seed(tmp_config.db_path, instrument="MNQ", timeframe="1h", time_=3600)
        _seed(tmp_config.db_path, instrument="MNQ", timeframe="5m", time_=300)
        _seed(tmp_config.db_path, instrument="MNQ", timeframe="1d", time_=86400)
        body = app.test_client().get("/api/chart/MNQ/timeframes-available").get_json()
        assert [tf["timeframe"] for tf in body["timeframes"]] == CANONICAL
    finally:
        pool.shutdown(wait=True)


def test_other_instruments_do_not_leak(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        _seed(tmp_config.db_path, instrument="ES", timeframe="1d", time_=86400, n=5)
        body = app.test_client().get("/api/chart/MNQ/timeframes-available").get_json()
        assert all(tf["count"] == 0 for tf in body["timeframes"])
    finally:
        pool.shutdown(wait=True)
