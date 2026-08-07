from tests.conftest import make_execution, seed_executions


def _seed_one_position(db_path):
    seed_executions(
        db_path,
        [
            make_execution(
                "a",
                account="Sim",
                timestamp=100,
                price=100.0,
                imported_at=100,
            ),
            make_execution(
                "b",
                account="Sim",
                timestamp=200,
                side="Sell",
                original_action="Sell",
                price=101.0,
                entry_exit="Exit",
                position_after="-",
                imported_at=200,
            ),
        ],
    )


def test_timeframes_available_route_is_wired(app):
    resp = app.test_client().get("/api/chart/MNQ/timeframes-available")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["instrument"] == "MNQ"
    assert "timeframes" in body
    assert "default_timeframe" in body
    names = [t["timeframe"] for t in body["timeframes"]]
    assert names == ["1m", "5m", "15m", "1h", "4h", "1d"]


def test_position_markers_route_is_wired(app, tmp_config):
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


def test_static_vendor_lightweight_charts_is_served(app):
    resp = app.test_client().get("/static/vendor/lightweight-charts.standalone.production.js")
    assert resp.status_code == 200
    # The standalone build defines the LightweightCharts global at least
    # once in its minified body. This is a cheap sanity check that the
    # vendor file is the right one and not e.g. an HTML error page.
    assert b"LightweightCharts" in resp.data


def test_static_price_chart_module_is_served(app):
    resp = app.test_client().get("/static/js/PriceChart.js")
    assert resp.status_code == 200
    assert b"export class PriceChart" in resp.data
