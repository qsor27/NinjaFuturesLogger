import pytest

from app import create_app


@pytest.fixture
def client(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        yield app.test_client()
    finally:
        services.stop()


def test_get_defaults_empty(client):
    resp = client.get("/api/filter-defaults")
    assert resp.status_code == 200
    assert resp.get_json() == {"positions": None, "stats": None}


def test_put_and_get_positions_default(client):
    resp = client.put(
        "/api/filter-defaults/positions",
        json={"accounts": ["Sim101"], "instrument": "MNQ", "side": "Long", "outcome": ""},
    )
    assert resp.status_code == 200

    resp = client.get("/api/filter-defaults")
    body = resp.get_json()
    assert body["positions"] == {
        "accounts": ["Sim101"],
        "instrument": "MNQ",
        "side": "Long",
        "outcome": "",
    }
    assert body["stats"] is None


def test_put_and_get_stats_default(client):
    resp = client.put(
        "/api/filter-defaults/stats",
        json={"accounts": ["A", "B"], "side": "Short"},
    )
    assert resp.status_code == 200

    body = client.get("/api/filter-defaults").get_json()
    assert body["stats"] == {"accounts": ["A", "B"], "side": "Short"}


def test_delete_clears_scope(client):
    client.put("/api/filter-defaults/positions", json={"accounts": ["A"]})
    resp = client.delete("/api/filter-defaults/positions")
    assert resp.status_code == 200

    body = client.get("/api/filter-defaults").get_json()
    assert body["positions"] is None


def test_delete_absent_scope_still_200(client):
    resp = client.delete("/api/filter-defaults/stats")
    assert resp.status_code == 200


def test_put_invalid_scope_returns_400(client):
    resp = client.put("/api/filter-defaults/bogus", json={"accounts": []})
    assert resp.status_code == 400


def test_put_unknown_body_key_returns_400(client):
    resp = client.put(
        "/api/filter-defaults/positions",
        json={"accounts": [], "evil": "x"},
    )
    assert resp.status_code == 400


def test_put_non_dict_body_returns_400(client):
    resp = client.put(
        "/api/filter-defaults/positions",
        json="not a dict",
    )
    assert resp.status_code == 400


def test_delete_invalid_scope_returns_400(client):
    resp = client.delete("/api/filter-defaults/bogus")
    assert resp.status_code == 400
