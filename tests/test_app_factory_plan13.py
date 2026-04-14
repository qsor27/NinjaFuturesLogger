from app import create_app
from db import connect
from models.execution import Execution
from services.import_db import bulk_insert_executions


def _seed_one_position(db_path):
    conn = connect(db_path)
    try:
        bulk_insert_executions(
            conn,
            [
                Execution(
                    nt_execution_id="a",
                    account="Sim",
                    instrument="MNQ",
                    timestamp=100,
                    side="Buy",
                    original_action="Buy",
                    quantity=1,
                    price=100.0,
                    commission=0.0,
                    entry_exit="Entry",
                    position_after="1 L",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=100,
                ),
                Execution(
                    nt_execution_id="b",
                    account="Sim",
                    instrument="MNQ",
                    timestamp=200,
                    side="Sell",
                    original_action="Sell",
                    quantity=1,
                    price=101.0,
                    commission=0.0,
                    entry_exit="Exit",
                    position_after="-",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=200,
                ),
            ],
        )
    finally:
        conn.close()


def test_timeframes_available_route_is_wired(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/chart/MNQ/timeframes-available")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["instrument"] == "MNQ"
        assert "timeframes" in body
        assert "default_timeframe" in body
        names = [t["timeframe"] for t in body["timeframes"]]
        assert names == ["1m", "5m", "15m", "1h", "4h", "1d"]
    finally:
        services.stop()


def test_position_markers_route_is_wired(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed_one_position(tmp_config.db_path)
        resp = app.test_client().get("/api/positions/Sim/MNQ/a/markers")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body == {
            "markers": [
                {"time": 100, "price": 100.0, "side": "Buy", "quantity": 1, "label": "a"},
                {"time": 200, "price": 101.0, "side": "Sell", "quantity": 1, "label": "b"},
            ]
        }
    finally:
        services.stop()


def test_static_vendor_lightweight_charts_is_served(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get(
            "/static/vendor/lightweight-charts.standalone.production.js"
        )
        assert resp.status_code == 200
        # The standalone build defines the LightweightCharts global at least
        # once in its minified body. This is a cheap sanity check that the
        # vendor file is the right one and not e.g. an HTML error page.
        assert b"LightweightCharts" in resp.data
    finally:
        services.stop()


def test_static_price_chart_module_is_served(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/static/js/PriceChart.js")
        assert resp.status_code == 200
        assert b"export class PriceChart" in resp.data
    finally:
        services.stop()
