from tests.conftest import make_execution, seed_executions


def _seed(db_path):
    seed_executions(
        db_path,
        [
            make_execution(
                "a",
                account="Sim",
                timestamp=100,
                quantity=2,
                price=100.0,
                position_after="2 L",
                imported_at=100,
            ),
            make_execution(
                "b",
                account="Sim",
                timestamp=200,
                side="Sell",
                original_action="Sell",
                quantity=2,
                price=101.5,
                entry_exit="Exit",
                position_after="-",
                imported_at=200,
            ),
        ],
    )


def test_markers_for_simple_long_position(app, tmp_config):
    _seed(tmp_config.db_path)
    resp = app.test_client().get("/api/positions/Sim/MNQ/a/markers")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "markers" in body
    markers = body["markers"]
    assert len(markers) == 2
    m_by_label = {m["label"]: m for m in markers}
    assert m_by_label["a"] == {
        "time": 100,
        "price": 100.0,
        "side": "Buy",
        "quantity": 2,
        "label": "a",
    }
    assert m_by_label["b"] == {
        "time": 200,
        "price": 101.5,
        "side": "Sell",
        "quantity": 2,
        "label": "b",
    }


def test_markers_unknown_position_returns_404(client):
    resp = client.get("/api/positions/Sim/MNQ/nope/markers")
    assert resp.status_code == 404


def test_markers_only_include_position_executions_not_other_pairs(app, tmp_config):
    _seed(tmp_config.db_path)
    # Add an unrelated execution on a different instrument; it must not
    # appear in the MNQ position's markers.
    seed_executions(
        tmp_config.db_path,
        [
            make_execution(
                "z",
                account="Sim",
                instrument="ES",
                timestamp=150,
                price=4500.0,
                imported_at=150,
            ),
        ],
    )
    resp = app.test_client().get("/api/positions/Sim/MNQ/a/markers")
    labels = {m["label"] for m in resp.get_json()["markers"]}
    assert labels == {"a", "b"}
