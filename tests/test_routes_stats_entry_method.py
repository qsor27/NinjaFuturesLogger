import pytest

from tests.conftest import make_execution, seed_executions

E0 = 1776070800  # 2026-04-13 session


def _entry(eid, ts, name):
    return make_execution(eid, account="Sim", timestamp=ts, price=100.0, order_name=name)


def _exit(eid, ts, price, name):
    return make_execution(
        eid,
        account="Sim",
        timestamp=ts,
        side="Sell",
        original_action="Sell",
        price=price,
        entry_exit="Exit",
        position_after="-",
        order_name=name,
    )


@pytest.fixture
def client(app, tmp_config):
    seed_executions(
        tmp_config.db_path,
        [
            # closed gate-market winner
            _entry("a1", E0, "GateMktNextOpen"),
            _exit("b1", E0 + 600, 110.0, "Target1"),
            # closed manual loser
            _entry("a2", E0 + 1200, "Entry"),
            _exit("b2", E0 + 1800, 95.0, "Stop1"),
            # open gate-limit position
            _entry("a3", E0 + 2400, "GateLmtNextOpen"),
        ],
    )
    return app.test_client()


def test_summary_filters_by_entry_method(client):
    body = client.get("/api/stats/summary?entry_method=market_next_open").get_json()
    assert body["total_positions"] == 1
    assert body["wins"] == 1


def test_summary_open_positions_respects_entry_method(client):
    assert client.get("/api/stats/summary").get_json()["open_positions"] == 1
    body = client.get("/api/stats/summary?entry_method=manual").get_json()
    assert body["open_positions"] == 0
    body = client.get("/api/stats/summary?entry_method=limit_next_open").get_json()
    assert body["open_positions"] == 1
    assert body["total_positions"] == 0


def test_by_entry_method_rows(client):
    resp = client.get("/api/stats/by-entry-method")
    assert resp.status_code == 200
    rows = resp.get_json()["rows"]
    assert [r["entry_method"] for r in rows] == [
        "market_next_open",
        "limit_next_open",
        "manual",
        "unknown",
    ]
    counts = {r["entry_method"]: r["position_count"] for r in rows}
    assert counts == {"market_next_open": 1, "limit_next_open": 0, "manual": 1, "unknown": 0}
    by = {r["entry_method"]: r for r in rows}
    assert by["market_next_open"]["total_pnl"] > 0
    assert by["manual"]["total_pnl"] < 0


def test_invalid_entry_method_is_400(client):
    resp = client.get("/api/stats/summary?entry_method=bogus")
    assert resp.status_code == 400
    assert "entry_method" in resp.get_json()["error"]


def test_empty_entry_method_means_all(client):
    body = client.get("/api/stats/summary?entry_method=").get_json()
    assert body["total_positions"] == 2
