import pytest
from flask import Flask

from db import connect
from services.ohlc.store import insert_many
from tests.conftest import make_bar, make_execution, seed_executions

ENTRY_TS = 100_000
BOUNDARY = 99_960
EXIT_TS = ENTRY_TS + 300


@pytest.fixture
def seeded(app: Flask):
    db_path = app.config["FTL_DB_PATH"]
    seed_executions(
        db_path,
        [
            make_execution("e1", timestamp=ENTRY_TS, side="Buy", entry_exit="Entry", price=100.0),
            make_execution(
                "x1",
                timestamp=EXIT_TS,
                side="Sell",
                entry_exit="Exit",
                price=101.0,
                position_after="-",
            ),
        ],
    )
    conn = connect(db_path)
    try:
        insert_many(
            conn,
            [make_bar(time=t) for t in range(BOUNDARY - 3600, EXIT_TS + 1800, 60)],
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _session(client):
    resp = client.post("/api/review/sessions")
    assert resp.status_code == 201
    return resp.get_json()["session_id"]


def test_session_create_and_next_card(client, seeded):
    sid = _session(client)
    resp = client.get(f"/api/review/next-card?session_id={sid}")
    assert resp.status_code == 200
    card = resp.get_json()["card"]
    assert card["entry_execution_id"] == "e1"
    assert card["side"] == "Long"
    assert card["entry_price"] == 100.0


def test_next_card_unknown_session_404(client, seeded):
    assert client.get("/api/review/next-card?session_id=999").status_code == 404


def test_next_card_empty_deck_204(client):
    sid = _session(client)
    assert client.get(f"/api/review/next-card?session_id={sid}").status_code == 204


def test_card_bars_cropped(client, seeded):
    sid = _session(client)
    resp = client.get(f"/api/review/cards/e1/bars?timeframe=1m&session_id={sid}")
    assert resp.status_code == 200
    bars = resp.get_json()["bars"]
    assert bars, "expected pre-call bars"
    assert max(b["time"] for b in bars) < BOUNDARY


def test_card_bars_bad_timeframe_400(client, seeded):
    sid = _session(client)
    resp = client.get(f"/api/review/cards/e1/bars?timeframe=4h&session_id={sid}")
    assert resp.status_code == 400


def test_reveal_gated_until_attempt(client, seeded):
    sid = _session(client)
    url = f"/api/review/cards/e1/bars?timeframe=1m&session_id={sid}&revealed=1"
    assert client.get(url).status_code == 403  # no attempt yet

    resp = client.post(
        "/api/review/attempts",
        json={"session_id": sid, "entry_execution_id": "e1", "call": "valid"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["reveal"]["exit_time"] == EXIT_TS
    assert body["reveal"]["exit_fills"][0]["price"] == 101.0
    # MNQ multiplier x 1 point x 1 qty, zero commission
    assert body["reveal"]["net_pnl"] == body["reveal"]["dollars_pnl"]

    resp = client.get(url)
    assert resp.status_code == 200
    times = [b["time"] for b in resp.get_json()["bars"]]
    assert max(times) > BOUNDARY  # the future is visible now


def test_attempt_validation(client, seeded):
    sid = _session(client)
    bad = client.post(
        "/api/review/attempts",
        json={"session_id": sid, "entry_execution_id": "e1", "call": "meh"},
    )
    assert bad.status_code == 400
    missing = client.post(
        "/api/review/attempts",
        json={"session_id": sid, "entry_execution_id": "ghost", "call": "valid"},
    )
    assert missing.status_code == 404


def test_attempt_on_open_position_409(client, seeded):
    seed_executions(
        client.application.config["FTL_DB_PATH"],
        [make_execution("e2", timestamp=EXIT_TS + 60, side="Buy", entry_exit="Entry")],
    )
    sid = _session(client)
    resp = client.post(
        "/api/review/attempts",
        json={"session_id": sid, "entry_execution_id": "e2", "call": "valid"},
    )
    assert resp.status_code == 409


def test_end_session_returns_both_summaries(client, seeded):
    sid = _session(client)
    client.post(
        "/api/review/attempts",
        json={"session_id": sid, "entry_execution_id": "e1", "call": "invalid"},
    )
    resp = client.post(f"/api/review/sessions/{sid}/end")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["session"]["invalid_won"]["count"] == 1
    assert body["all_time"]["attempts"] >= 1
    assert client.post("/api/review/sessions/999/end").status_code == 404


def test_review_page_renders(client):
    resp = client.get("/review")
    assert resp.status_code == 200
    assert b"review" in resp.data.lower()
