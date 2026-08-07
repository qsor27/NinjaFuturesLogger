from db import connect
from tests.conftest import make_execution, seed_executions


def _ex(exid, account, instrument, ts, side, action, ex_mark, pos_col):
    return make_execution(
        exid,
        account=account,
        instrument=instrument,
        timestamp=ts,
        side=side,
        original_action=action,
        quantity=1,
        price=100.0,
        entry_exit=ex_mark,
        position_after=pos_col,
        imported_at=ts,
    )


def test_list_default_pagination(app, tmp_config):
    seed_executions(
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


def test_list_account_filter(app, tmp_config):
    seed_executions(
        tmp_config.db_path,
        [
            _ex("a", "X", "MNQ", 100, "Buy", "Buy", "Entry", "1 L"),
            _ex("b", "X", "MNQ", 200, "Sell", "Sell", "Exit", "-"),
            _ex("c", "Y", "MNQ", 300, "Buy", "Buy", "Entry", "1 L"),
            _ex("d", "Y", "MNQ", 400, "Sell", "Sell", "Exit", "-"),
        ],
    )
    # Legacy single-value URL keeps working (one-element getlist).
    resp = app.test_client().get("/api/positions?account=Y")
    body = resp.get_json()
    assert body["page"]["total"] == 1
    assert body["positions"][0]["account"] == "Y"

    # Multi-value URL: repeated `account=` params return the union.
    resp = app.test_client().get("/api/positions?account=X&account=Y")
    body = resp.get_json()
    assert body["page"]["total"] == 2
    returned = sorted(p["account"] for p in body["positions"])
    assert returned == ["X", "Y"]

    # Empty URL still returns everything.
    resp = app.test_client().get("/api/positions")
    body = resp.get_json()
    assert body["page"]["total"] == 2


def test_list_pagination_page_and_size(app, tmp_config):
    rows = []
    for i in range(6):
        rows.append(_ex(f"e{i}", "A", "MNQ", 100 + i * 10, "Buy", "Buy", "Entry", "1 L"))
        rows.append(_ex(f"x{i}", "A", "MNQ", 105 + i * 10, "Sell", "Sell", "Exit", "-"))
    seed_executions(tmp_config.db_path, rows)
    resp = app.test_client().get("/api/positions?page=2&page_size=2")
    body = resp.get_json()
    assert body["page"]["total"] == 6
    assert body["page"]["page"] == 2
    assert len(body["positions"]) == 2


def test_list_outcome_filter(app, tmp_config):
    seed_executions(
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


def test_list_rejects_unknown_outcome(client):
    resp = client.get("/api/positions?outcome=bogus")
    assert resp.status_code == 400


def test_filters_endpoint(app, tmp_config):
    seed_executions(
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


def test_list_session_date_range_filter(app, tmp_config):
    # 2026-04-13 09:00 UTC (ts 1776070800) -> session 2026-04-13
    # 2026-04-14 09:00 UTC (ts 1776157200) -> session 2026-04-14
    seed_executions(
        tmp_config.db_path,
        [
            _ex("a", "Sim", "MNQ", 1776070800, "Buy", "Buy", "Entry", "1 L"),
            _ex("b", "Sim", "MNQ", 1776070860, "Sell", "Sell", "Exit", "-"),
            _ex("c", "Sim", "MNQ", 1776157200, "Buy", "Buy", "Entry", "1 L"),
            _ex("d", "Sim", "MNQ", 1776157260, "Sell", "Sell", "Exit", "-"),
        ],
    )
    client = app.test_client()

    resp = client.get("/api/positions?session_date_from=2026-04-13&session_date_to=2026-04-13")
    assert resp.status_code == 200
    assert resp.get_json()["page"]["total"] == 1

    resp = client.get("/api/positions?session_date_from=2026-04-13&session_date_to=2026-04-14")
    assert resp.get_json()["page"]["total"] == 2

    resp = client.get("/api/positions?session_date_from=2026-04-14")
    assert resp.get_json()["page"]["total"] == 1


def test_list_session_date_range_bad_ordering_returns_400(client):
    resp = client.get("/api/positions?session_date_from=2026-04-16&session_date_to=2026-04-01")
    assert resp.status_code == 400
    assert "session_date_from" in resp.get_json()["error"]


def test_list_session_date_range_bad_format_returns_400(client):
    resp = client.get("/api/positions?session_date_from=not-a-date")
    assert resp.status_code == 400


def test_list_rejects_bad_paging_params(client):
    assert client.get("/api/positions?page=abc").status_code == 400
    assert client.get("/api/positions?page=0").status_code == 400
    assert client.get("/api/positions?page_size=0").status_code == 400
    assert client.get("/api/positions?page_size=501").status_code == 400
