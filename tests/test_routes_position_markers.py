from app import create_app
from db import connect
from models.execution import Execution
from services.import_db import bulk_insert_executions


def _seed(db_path):
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
                    quantity=2,
                    price=100.0,
                    commission=0.0,
                    entry_exit="Entry",
                    position_after="2 L",
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
                    quantity=2,
                    price=101.5,
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


def test_markers_for_simple_long_position(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
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
    finally:
        services.stop()


def test_markers_unknown_position_returns_404(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/positions/Sim/MNQ/nope/markers")
        assert resp.status_code == 404
    finally:
        services.stop()


def test_markers_only_include_position_executions_not_other_pairs(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        # Add an unrelated execution on a different instrument; it must not
        # appear in the MNQ position's markers.
        conn = connect(tmp_config.db_path)
        try:
            bulk_insert_executions(
                conn,
                [
                    Execution(
                        nt_execution_id="z",
                        account="Sim",
                        instrument="ES",
                        timestamp=150,
                        side="Buy",
                        original_action="Buy",
                        quantity=1,
                        price=4500.0,
                        commission=0.0,
                        entry_exit="Entry",
                        position_after="1 L",
                        source_order_id=None,
                        source_filename="f.csv",
                        imported_at=150,
                    ),
                ],
            )
        finally:
            conn.close()
        resp = app.test_client().get("/api/positions/Sim/MNQ/a/markers")
        labels = {m["label"] for m in resp.get_json()["markers"]}
        assert labels == {"a", "b"}
    finally:
        services.stop()
