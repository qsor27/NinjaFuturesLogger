import pytest

from tests.conftest import make_execution, seed_executions

E0 = 1776070800  # 2026-04-13 session


def _rule(**over):
    base = dict(
        metric="losses", scope="session", comparator=">=", threshold=2, action="stop_session"
    )
    base.update(over)
    return base


@pytest.fixture
def seeded(app):
    db_path = app.config["FTL_DB_PATH"]
    rows = []
    for i, exit_px in enumerate(
        [95.0, 95.0, 105.0]
    ):  # 5-point moves clear the commission scratch band
        base = E0 + i * 1200
        rows.append(make_execution(f"a{i}", account="Sim", timestamp=base, commission=1.0))
        rows.append(
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
            )
        )
    seed_executions(db_path, rows)
    return db_path


def test_vocabulary(client):
    resp = client.get("/api/simulations/vocabulary")
    assert resp.status_code == 200
    body = resp.get_json()
    assert {m["value"] for m in body["metrics"]} >= {"losses", "time_of_day"}
    assert body["max_rules"] == 10


def test_crud_lifecycle(client):
    assert client.get("/api/simulations").get_json() == {"simulations": []}
    resp = client.post("/api/simulations", json={"name": "Plan A", "rules": [_rule()]})
    assert resp.status_code == 201
    created = resp.get_json()
    sid = created["simulation_id"]
    assert created["rules"][0]["label"] == "losses in session >= 2 -> stop for session"

    assert client.get(f"/api/simulations/{sid}").get_json()["name"] == "Plan A"
    dup = client.post("/api/simulations", json={"name": "Plan A", "rules": [_rule()]})
    assert dup.status_code == 409

    put = client.put(
        f"/api/simulations/{sid}", json={"name": "Plan B", "rules": [_rule(threshold=3)]}
    )
    assert put.status_code == 200
    assert put.get_json()["rules"][0]["threshold"] == 3
    assert [d["name"] for d in client.get("/api/simulations").get_json()["simulations"]] == [
        "Plan B"
    ]

    assert client.delete(f"/api/simulations/{sid}").status_code == 204
    assert client.delete(f"/api/simulations/{sid}").status_code == 404
    assert client.get(f"/api/simulations/{sid}").status_code == 404
    assert (
        client.put(f"/api/simulations/{sid}", json={"name": "x", "rules": [_rule()]}).status_code
        == 404
    )


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "rules": [_rule(metric="bogus")]},
        {"name": "x", "rules": [_rule(threshold="2")]},
        {"name": "x", "rules": [_rule(action="pause_minutes")]},
        {"name": "x", "rules": [_rule(metric="time_of_day", threshold="11:00", scope="week")]},
        {"name": "x", "rules": [_rule()] * 11},
        {"name": "   ", "rules": [_rule()]},
        {"name": "x"},
        {"rules": [_rule()]},
        [],
    ],
)
def test_create_validation_400(client, body):
    resp = client.post("/api/simulations", json=body)
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_400_details_locate_the_bad_rule(client):
    resp = client.post(
        "/api/simulations", json={"name": "x", "rules": [_rule(), _rule(threshold=-1)]}
    )
    assert resp.status_code == 400
    details = resp.get_json()["details"]
    assert any(d["loc"][:2] == ["rules", "1"] for d in details)


def test_run_unsaved(client, seeded):
    resp = client.post(
        "/api/simulations/run",
        json={"rules": [_rule()], "accounts": ["Sim"], "from": "2026-04-01", "to": "2026-04-30"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["inputs"]["positions_considered"] == 3
    assert body["inputs"]["from_date"] == "2026-04-01"
    assert [s["entry_execution_id"] for s in body["skipped"]] == ["a2"]
    assert body["by_day"][0]["session_date"] == "2026-04-13"


def test_run_unsaved_bad_date_400(client):
    resp = client.post("/api/simulations/run", json={"rules": [_rule()], "from": "nope"})
    assert resp.status_code == 400


def test_run_saved_with_query_filter(client, seeded):
    sid = client.post("/api/simulations", json={"name": "P", "rules": [_rule()]}).get_json()[
        "simulation_id"
    ]
    ok = client.get(f"/api/simulations/{sid}/run?account=Sim&from=2026-04-01")
    assert ok.status_code == 200
    assert ok.get_json()["inputs"]["positions_considered"] == 3
    empty = client.get(f"/api/simulations/{sid}/run?from=2030-01-01")
    assert empty.status_code == 200
    assert empty.get_json()["inputs"]["positions_considered"] == 0
    assert empty.get_json()["actual"]["summary"]["total_positions"] == 0
    assert client.get("/api/simulations/999/run").status_code == 404
    assert client.get(f"/api/simulations/{sid}/run?side=Sideways").status_code == 400
