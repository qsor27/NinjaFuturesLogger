import pytest

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


def test_executions_endpoint_entry_rows_have_null_pnl(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
        assert resp.status_code == 200
        body = resp.get_json()
        entry = next(e for e in body["executions"] if e["entry_exit"] == "Entry")
        assert entry["avg_entry_price"] is None
        assert entry["pnl_points"] is None
        assert entry["pnl_dollars_net"] is None
    finally:
        services.stop()


def test_executions_endpoint_exit_rows_have_pnl(tmp_config):
    # MNQ Long: entry 100.0, exit 101.0, qty 1, commission 0
    # MNQ multiplier = 2.0
    # pnl_points = (101.0 - 100.0) * 1 * 1 = 1.0
    # pnl_dollars_net = 1.0 * 2.0 - 0.0 = 2.0
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
        assert resp.status_code == 200
        body = resp.get_json()
        exit_row = next(e for e in body["executions"] if e["entry_exit"] == "Exit")
        assert exit_row["avg_entry_price"] == pytest.approx(100.0)
        assert exit_row["pnl_points"] == pytest.approx(1.0)
        assert exit_row["pnl_dollars_net"] == pytest.approx(2.0)
    finally:
        services.stop()


def test_executions_endpoint_exit_pnl_uses_commission_fallback(tmp_path, tmp_config):
    import json

    from services.instruments import set_registry_path

    instruments_json = tmp_path / "instruments.json"
    instruments_json.write_text(
        json.dumps(
            {
                "MNQ": {
                    "display_name": "Micro E-mini Nasdaq-100",
                    "multiplier": 2.0,
                    "tick_size": 0.25,
                    "commission_per_contract": 1.08,
                    "sources": {
                        "yfinance": {"continuous": "MNQ=F", "contract_template": None},
                        "stooq": {"continuous": "mnq.f", "contract_template": None},
                    },
                    "session": {
                        "timezone": "America/Chicago",
                        "open": "17:00",
                        "close": "16:00",
                        "daily_break_start": "16:00",
                        "daily_break_end": "17:00",
                    },
                }
            }
        )
    )
    app, services = create_app(tmp_config, start_background=False)
    set_registry_path(instruments_json)
    try:
        _seed(tmp_config.db_path)  # seeds MNQ with commission=0.0
        resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
        body = resp.get_json()
        exit_row = next(e for e in body["executions"] if e["entry_exit"] == "Exit")
        # pnl_points = 1.0, multiplier = 2.0, eff_comm = 1.08 × 1 = 1.08
        # pnl_dollars_net = 2.0 - 1.08 = 0.92
        assert exit_row["pnl_dollars_net"] == pytest.approx(0.92)
    finally:
        services.stop()
