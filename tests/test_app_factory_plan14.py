from db import connect
from models.bar import Bar
from services.ohlc.store import insert_many


def test_ohlc_blueprint_registered_and_chart_endpoint_works(app, tmp_config):
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


def test_sources_endpoint_lists_yfinance_and_stooq(app):
    resp = app.test_client().get("/api/ohlc/sources")
    assert resp.status_code == 200
    names = {s["name"] for s in resp.get_json()["sources"]}
    assert names == {"yfinance", "stooq"}
