from app import create_app
from db import connect
from models.execution import Execution
from services.flags import set_reviewed
from services.import_db import bulk_insert_executions
from services.notes import upsert_note


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


def test_detail_attaches_notes_and_reviewed(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        upsert_note(tmp_config.db_path, execution_id="a", note="setup", now=150)
        set_reviewed(tmp_config.db_path, execution_id="a", reviewed=True, now=151)
        resp = app.test_client().get("/api/positions/Sim/MNQ/a")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["position"]["entry_execution_id"] == "a"
        assert body["notes"] == {"a": "setup"}
        assert body["reviewed"] == {"a": True}
        assert body["custom_fields"] == {"entry": {}, "per_execution": [], "definitions": []}
    finally:
        services.stop()


def test_detail_not_found(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/positions/Sim/MNQ/nope")
        assert resp.status_code == 404
    finally:
        services.stop()


def test_detail_executions_endpoint(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
        assert resp.status_code == 200
        body = resp.get_json()
        assert [e["nt_execution_id"] for e in body["executions"]] == ["a", "b"]
    finally:
        services.stop()
