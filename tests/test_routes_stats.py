import pytest

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
                    timestamp=1776070800,  # 2026-04-13 09:00 UTC
                    side="Buy",
                    original_action="Buy",
                    quantity=1,
                    price=100.0,
                    commission=2.0,
                    entry_exit="Entry",
                    position_after="1 L",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=1,
                ),
                Execution(
                    nt_execution_id="b",
                    account="Sim",
                    instrument="MNQ",
                    timestamp=1776071400,
                    side="Sell",
                    original_action="Sell",
                    quantity=1,
                    price=110.0,
                    commission=2.0,
                    entry_exit="Exit",
                    position_after="-",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=2,
                ),
            ],
        )
    finally:
        conn.close()


@pytest.fixture
def client(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    _seed(tmp_config.db_path)
    try:
        yield app.test_client()
    finally:
        services.stop()


def test_summary(client):
    resp = client.get("/api/stats/summary")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_positions"] == 1
    assert body["wins"] == 1
    assert "skipped_no_multiplier" in body
    assert "open_positions" in body


def test_summary_with_account_filter(client):
    resp = client.get("/api/stats/summary?account=Sim")
    assert resp.status_code == 200
    assert resp.get_json()["total_positions"] == 1


def test_summary_unknown_account_returns_zero_not_error(client):
    resp = client.get("/api/stats/summary?account=DoesNotExist")
    assert resp.status_code == 200
    assert resp.get_json()["total_positions"] == 0


def test_summary_invalid_date_400(client):
    resp = client.get("/api/stats/summary?from=not-a-date")
    assert resp.status_code == 400
    assert "from" in resp.get_json()["error"].lower()


def test_by_instrument(client):
    resp = client.get("/api/stats/by-instrument")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["rows"]) == 1
    assert body["rows"][0]["instrument"] == "MNQ"


def test_by_day(client):
    resp = client.get("/api/stats/by-day")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["granularity"] == "day"


def test_by_week(client):
    resp = client.get("/api/stats/by-week")
    assert resp.status_code == 200
    assert resp.get_json()["granularity"] == "week"


def test_by_month(client):
    resp = client.get("/api/stats/by-month")
    assert resp.status_code == 200
    assert resp.get_json()["granularity"] == "month"


def test_by_hour(client):
    resp = client.get("/api/stats/by-hour")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["timezone"] == "America/Chicago"
    assert len(body["buckets"]) == 24


def test_by_side(client):
    resp = client.get("/api/stats/by-side")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["long"]["position_count"] == 1
    assert body["short"]["position_count"] == 0


def test_equity_curve(client):
    resp = client.get("/api/stats/equity-curve")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "series" in body
    assert len(body["series"]) == 1
    assert body["series"][0]["account"] == "Sim"
    assert len(body["series"][0]["points"]) == 1


def test_distribution(client):
    resp = client.get("/api/stats/distribution")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["bucket_count"] == 10
    assert len(body["buckets"]) == 10


def _seed_two_accounts(db_path):
    conn = connect(db_path)
    try:
        bulk_insert_executions(
            conn,
            [
                Execution(
                    nt_execution_id="a1",
                    account="A",
                    instrument="MNQ",
                    timestamp=1776070800,
                    side="Buy",
                    original_action="Buy",
                    quantity=1,
                    price=100.0,
                    commission=2.0,
                    entry_exit="Entry",
                    position_after="1 L",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=1,
                ),
                Execution(
                    nt_execution_id="a2",
                    account="A",
                    instrument="MNQ",
                    timestamp=1776071400,
                    side="Sell",
                    original_action="Sell",
                    quantity=1,
                    price=110.0,
                    commission=2.0,
                    entry_exit="Exit",
                    position_after="-",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=2,
                ),
                Execution(
                    nt_execution_id="b1",
                    account="B",
                    instrument="MNQ",
                    timestamp=1776072000,
                    side="Buy",
                    original_action="Buy",
                    quantity=1,
                    price=100.0,
                    commission=2.0,
                    entry_exit="Entry",
                    position_after="1 L",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=3,
                ),
                Execution(
                    nt_execution_id="b2",
                    account="B",
                    instrument="MNQ",
                    timestamp=1776072600,
                    side="Sell",
                    original_action="Sell",
                    quantity=1,
                    price=105.0,
                    commission=2.0,
                    entry_exit="Exit",
                    position_after="-",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=4,
                ),
            ],
        )
    finally:
        conn.close()


def test_stats_summary_multi_account(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    _seed_two_accounts(tmp_config.db_path)
    try:
        c = app.test_client()

        # Legacy single account
        resp = c.get("/api/stats/summary?account=A")
        assert resp.status_code == 200
        assert resp.get_json()["total_positions"] == 1

        # Multi-account returns union
        resp = c.get("/api/stats/summary?account=A&account=B")
        assert resp.status_code == 200
        assert resp.get_json()["total_positions"] == 2

        # No account param returns everything
        resp = c.get("/api/stats/summary")
        assert resp.status_code == 200
        assert resp.get_json()["total_positions"] == 2
    finally:
        services.stop()
