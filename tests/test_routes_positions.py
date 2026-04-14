from pathlib import Path

import pytest
from flask import Flask

from db import connect
from migrations import run_migrations
from models.execution import Execution
from routes.positions import build_positions_blueprint
from services.import_db import bulk_insert_executions


@pytest.fixture
def app(tmp_path: Path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    run_migrations(conn, Path("migrations"))
    conn.close()
    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = str(db_path)
    app.register_blueprint(build_positions_blueprint())
    return app, db_path


def _ex(
    eid,
    side,
    qty,
    ts,
    *,
    account="Sim101",
    instrument="MNQ",
    position_after="1 L",
    entry_exit="Entry",
    price=4000.0,
):
    return Execution(
        nt_execution_id=eid,
        account=account,
        instrument=instrument,
        timestamp=ts,
        side=side,
        original_action=side,
        quantity=qty,
        price=price,
        commission=0.0,
        entry_exit=entry_exit,
        position_after=position_after,
        source_order_id=None,
        source_filename="f.csv",
        imported_at=ts,
    )


def test_list_empty(app):
    app_, _ = app
    resp = app_.test_client().get("/api/positions")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["positions"] == []
    assert body["page"]["total"] == 0


def test_list_returns_all_positions(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        bulk_insert_executions(
            conn,
            [
                _ex("a", "Buy", 1, 100, position_after="1 L"),
                _ex("b", "Sell", 1, 200, entry_exit="Exit", position_after="-"),
            ],
        )
    finally:
        conn.close()
    resp = app_.test_client().get("/api/positions")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["positions"]) == 1
    assert body["positions"][0]["entry_execution_id"] == "a"


def test_list_filters_by_account(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        bulk_insert_executions(
            conn,
            [
                _ex("a", "Buy", 1, 100, account="Sim101", position_after="1 L"),
                _ex(
                    "b",
                    "Sell",
                    1,
                    200,
                    account="Sim101",
                    entry_exit="Exit",
                    position_after="-",
                ),
                _ex("c", "Buy", 1, 300, account="APEX-1", position_after="1 L"),
                _ex(
                    "d",
                    "Sell",
                    1,
                    400,
                    account="APEX-1",
                    entry_exit="Exit",
                    position_after="-",
                ),
            ],
        )
    finally:
        conn.close()
    resp = app_.test_client().get("/api/positions?account=APEX-1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["positions"]) == 1
    assert body["positions"][0]["account"] == "APEX-1"


def test_get_position_by_natural_key(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        bulk_insert_executions(
            conn,
            [
                _ex("a", "Buy", 1, 100, position_after="1 L"),
                _ex("b", "Sell", 1, 200, entry_exit="Exit", position_after="-"),
            ],
        )
    finally:
        conn.close()
    resp = app_.test_client().get("/api/positions/Sim101/MNQ/a")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["position"]["entry_execution_id"] == "a"


def test_get_position_404(app):
    app_, _ = app
    resp = app_.test_client().get("/api/positions/Sim101/MNQ/nope")
    assert resp.status_code == 404
