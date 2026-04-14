from app import create_app
from db import connect
from models.execution import Execution
from services.import_db import bulk_insert_executions


def _ex(exid, account, instrument, ts, side, action, ex_mark, pos_col):
    return Execution(
        nt_execution_id=exid,
        account=account,
        instrument=instrument,
        timestamp=ts,
        side=side,
        original_action=action,
        quantity=1,
        price=100.0,
        commission=0.0,
        entry_exit=ex_mark,
        position_after=pos_col,
        source_order_id=None,
        source_filename="f.csv",
        imported_at=ts,
    )


def _seed(db_path, execs):
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, execs)
    finally:
        conn.close()


def test_list_default_pagination(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(
            tmp_config.db_path,
            [
                _ex("a", "Sim", "MNQ", 100, "Buy", "Buy", "Entry", "1 L"),
                _ex("b", "Sim", "MNQ", 200, "Sell", "Sell", "Exit", "-"),
            ],
        )
        resp = app.test_client().get("/api/positions")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "positions" in body
        assert "page" in body
        assert body["page"]["page"] == 1
        assert body["page"]["page_size"] == 50
        assert body["page"]["total"] == 1
    finally:
        services.stop()


def test_list_account_filter(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(
            tmp_config.db_path,
            [
                _ex("a", "X", "MNQ", 100, "Buy", "Buy", "Entry", "1 L"),
                _ex("b", "X", "MNQ", 200, "Sell", "Sell", "Exit", "-"),
                _ex("c", "Y", "MNQ", 300, "Buy", "Buy", "Entry", "1 L"),
                _ex("d", "Y", "MNQ", 400, "Sell", "Sell", "Exit", "-"),
            ],
        )
        resp = app.test_client().get("/api/positions?account=Y")
        body = resp.get_json()
        assert body["page"]["total"] == 1
        assert body["positions"][0]["account"] == "Y"
    finally:
        services.stop()


def test_list_pagination_page_and_size(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        rows = []
        for i in range(6):
            rows.append(_ex(f"e{i}", "A", "MNQ", 100 + i * 10, "Buy", "Buy", "Entry", "1 L"))
            rows.append(_ex(f"x{i}", "A", "MNQ", 105 + i * 10, "Sell", "Sell", "Exit", "-"))
        _seed(tmp_config.db_path, rows)
        resp = app.test_client().get("/api/positions?page=2&page_size=2")
        body = resp.get_json()
        assert body["page"]["total"] == 6
        assert body["page"]["page"] == 2
        assert len(body["positions"]) == 2
    finally:
        services.stop()


def test_list_outcome_filter(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(
            tmp_config.db_path,
            [
                _ex("a", "A", "MNQ", 100, "Buy", "Buy", "Entry", "1 L"),
                _ex("b", "A", "MNQ", 200, "Sell", "Sell", "Exit", "-"),
            ],
        )
        conn = connect(tmp_config.db_path)
        try:
            conn.execute("UPDATE executions SET price = 200.0 WHERE nt_execution_id = 'b'")
        finally:
            conn.close()
        resp = app.test_client().get("/api/positions?outcome=winner")
        body = resp.get_json()
        assert body["page"]["total"] == 1
        resp2 = app.test_client().get("/api/positions?outcome=loser")
        assert resp2.get_json()["page"]["total"] == 0
    finally:
        services.stop()


def test_list_rejects_unknown_outcome(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/positions?outcome=bogus")
        assert resp.status_code == 400
    finally:
        services.stop()


def test_filters_endpoint(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(
            tmp_config.db_path,
            [
                _ex("a", "X", "MNQ", 100, "Buy", "Buy", "Entry", "1 L"),
                _ex("b", "Y", "ES", 200, "Buy", "Buy", "Entry", "1 L"),
            ],
        )
        resp = app.test_client().get("/api/positions/filters")
        assert resp.status_code == 200
        body = resp.get_json()
        assert set(body["accounts"]) == {"X", "Y"}
        assert set(body["instruments"]) == {"MNQ", "ES"}
    finally:
        services.stop()
