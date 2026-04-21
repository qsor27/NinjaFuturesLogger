from app import create_app
from db import connect
from models.bar import Bar
from services.ohlc.store import insert_many


def _seed_position_and_bars(db_path):
    """Seed one closed long position (100→102) and 1m bars covering it."""
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp,"
            " side, original_action, quantity, price, commission, entry_exit,"
            " position_after, source_order_id, source_filename, imported_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("E1", "A", "TEST", 1000, "Buy", "Buy", 1, 100.0, 0.0, "Entry", 1, "O1", "f.csv", 0),
        )
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp,"
            " side, original_action, quantity, price, commission, entry_exit,"
            " position_after, source_order_id, source_filename, imported_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("E2", "A", "TEST", 2000, "Sell", "Sell", 1, 102.0, 0.0, "Exit", 0, "O2", "f.csv", 0),
        )
        insert_many(
            conn,
            [
                Bar(
                    instrument="TEST",
                    timeframe="1m",
                    time=1060,
                    open=100.5,
                    high=103.0,
                    low=99.0,
                    close=101.0,
                    volume=0,
                    source="test",
                ),
                Bar(
                    instrument="TEST",
                    timeframe="1m",
                    time=1120,
                    open=101.0,
                    high=102.0,
                    low=100.0,
                    close=102.0,
                    volume=0,
                    source="test",
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_mfe_mae_endpoint_returns_result_for_closed_position(tmp_config):
    app, _services = create_app(tmp_config, start_background=False)
    _seed_position_and_bars(tmp_config.db_path)
    client = app.test_client()
    resp = client.get("/api/positions/A/TEST/E1/mfe-mae")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["result"] is not None
    assert body["result"]["mfe_dollars"] == 3.0
    assert body["result"]["mae_dollars"] == -1.0


def test_mfe_mae_endpoint_404_for_unknown_position(tmp_config):
    app, _services = create_app(tmp_config, start_background=False)
    client = app.test_client()
    resp = client.get("/api/positions/A/TEST/DOES_NOT_EXIST/mfe-mae")
    assert resp.status_code == 404


def test_mfe_mae_endpoint_never_imports_fetch_range():
    """Rule 6: the detail route must not pull fetch_range into its top-level imports."""
    import routes.positions as mod

    assert (
        "fetch_range" not in mod.__dict__
    ), "routes/positions.py must not import fetch_range at module level — Rule 6"


def test_efficiency_distribution_route_empty_dataset(tmp_config):
    app, _services = create_app(tmp_config, start_background=False)
    client = app.test_client()
    resp = client.get("/api/stats/efficiency-distribution")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["capture_buckets"]) == 10
    assert len(body["risk_buckets"]) == 10
    assert all(b["count"] == 0 for b in body["capture_buckets"])
    assert body["n_winners"] == 0
    assert body["n_losers"] == 0
    assert body["n_below_coverage"] == 0
