import pytest

from app import create_app


@pytest.fixture
def client(tmp_config):
    app, _services = create_app(tmp_config, start_background=False)
    with app.test_client() as c:
        yield c, tmp_config.db_path


def _insert_attempt(db_path, *, aid="A1"):
    from db import connect

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO fetch_attempts (id, trigger, instrument, timeframe,"
        " range_start, range_end, started_at, completed_at, gaps_found,"
        " bars_written, final_status, error)"
        " VALUES (?, 'maintainer', 'MNQ', '1m', 0, 60, 100, 200, 1, 1,"
        " 'ok', NULL)",
        (aid,),
    )
    conn.execute(
        "INSERT INTO fetch_source_attempts (attempt_id, gap_start, gap_end,"
        " source, outcome, bars_returned, duration_ms, http_status,"
        " error_class, error)"
        " VALUES (?, 0, 60, 'yfinance', 'ok', 1, 50, 200, NULL, NULL)",
        (aid,),
    )
    conn.close()


def _insert_gap(db_path, *, instrument="MNQ"):
    from db import connect

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO ohlc_gap_reports (instrument, timeframe, gap_start,"
        " gap_end, first_seen_at, attempt_count, next_retry_at, state)"
        " VALUES (?, '1m', 0, 60, 100, 0, 200, 'open')",
        (instrument,),
    )
    conn.close()


def test_get_attempts_returns_per_source_rows(client):
    c, db_path = client
    _insert_attempt(db_path, aid="A1")
    resp = c.get("/api/ohlc/attempts")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "attempts" in body
    assert len(body["attempts"]) == 1
    a = body["attempts"][0]
    assert a["id"] == "A1"
    assert a["trigger"] == "maintainer"
    assert "sources" in a
    assert len(a["sources"]) == 1
    assert a["sources"][0]["source"] == "yfinance"


def test_get_gaps_open_only(client):
    c, db_path = client
    _insert_gap(db_path, instrument="MNQ")
    resp = c.get("/api/ohlc/gaps")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["gaps"][0]["instrument"] == "MNQ"
    assert body["gaps"][0]["state"] == "open"


def test_post_retry_reopens_and_schedules(client):
    c, db_path = client
    _insert_gap(db_path)
    from db import connect

    conn = connect(db_path)
    gap_id = conn.execute("SELECT id FROM ohlc_gap_reports").fetchone()["id"]
    conn.close()
    resp = c.post(f"/api/ohlc/gaps/{gap_id}/retry")
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["ok"] is True
