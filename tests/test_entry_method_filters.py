import pytest

from services.position_filters import PositionFilter, apply_filters
from tests.conftest import make_execution, make_position, seed_executions

E0 = 1776070800  # 2026-04-13 session


def test_apply_filters_entry_method():
    ps = [
        make_position(entry_execution_id="m", entry_method="market_next_open"),
        make_position(entry_execution_id="x", entry_method="manual"),
    ]
    kept = apply_filters(ps, PositionFilter(entry_method="manual"))
    assert [p.entry_execution_id for p in kept] == ["x"]


def _pair(i, entry_name, exit_px):
    base = E0 + i * 1200
    return [
        make_execution(
            f"a{i}", account="Sim", timestamp=base, commission=1.0, order_name=entry_name
        ),
        make_execution(
            f"b{i}",
            account="Sim",
            timestamp=base + 600,
            side="Sell",
            original_action="Sell",
            price=exit_px,
            commission=1.0,
            entry_exit="Exit",
            position_after="-",
            order_name="Target1",
        ),
    ]


@pytest.fixture
def seeded(app):
    rows = (
        _pair(0, "GateMktNextOpen", 105.0)
        + _pair(1, "GateLmtNextOpen", 95.0)
        + _pair(2, "Entry", 105.0)
    )
    seed_executions(app.config["FTL_DB_PATH"], rows)


def _rule():
    return dict(
        metric="losses", scope="session", comparator=">=", threshold=2, action="stop_session"
    )


def test_simulation_run_filters_entry_method(client, seeded):
    resp = client.post(
        "/api/simulations/run",
        json={"rules": [_rule()], "accounts": ["Sim"], "entry_method": "limit_next_open"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["inputs"]["positions_considered"] == 1


def test_simulation_run_invalid_entry_method_400(client, seeded):
    resp = client.post("/api/simulations/run", json={"rules": [_rule()], "entry_method": "bogus"})
    assert resp.status_code == 400
    assert "entry_method" in resp.get_json()["error"]


def test_positions_list_filters_entry_method(client, seeded):
    resp = client.get("/api/positions?entry_method=market_next_open")
    assert resp.status_code == 200
    assert resp.get_json()["page"]["total"] == 1


def test_positions_list_invalid_entry_method_400(client, seeded):
    resp = client.get("/api/positions?entry_method=bogus")
    assert resp.status_code == 400
    assert "entry_method" in resp.get_json()["error"]
