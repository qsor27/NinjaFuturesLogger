import pytest

from app import create_app


@pytest.fixture
def client(tmp_config):
    app, _services = create_app(tmp_config, start_background=False)
    with app.test_client() as c:
        yield c, tmp_config.db_path


def _insert_bars(db_path, *, times, instrument="MNQ JUN26", timeframe="1m"):
    from db import connect

    conn = connect(db_path)
    for t in times:
        conn.execute(
            "INSERT INTO bars (instrument, timeframe, time, open, high, low,"
            " close, volume, source, fetched_at)"
            " VALUES (?, ?, ?, 1, 1, 1, 1, 0, 'test', ?)",
            (instrument, timeframe, t, t),
        )
    conn.close()


def _count_bars(db_path, *, instrument, timeframe, start, end):
    from db import connect

    conn = connect(db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM bars WHERE instrument=? AND timeframe=?"
        " AND time >= ? AND time < ?",
        (instrument, timeframe, start, end),
    ).fetchone()[0]
    conn.close()
    return n


def test_delete_removes_bars_in_window(client):
    c, db_path = client
    _insert_bars(db_path, times=[0, 60, 120, 180, 240])
    resp = c.post(
        "/api/ohlc/bars/delete",
        json={"instrument": "MNQ JUN26", "timeframe": "1m", "start": 60, "end": 240},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["deleted"] == 3  # 60, 120, 180

    # Bars outside the window remain.
    assert _count_bars(db_path, instrument="MNQ JUN26", timeframe="1m", start=0, end=60) == 1
    assert _count_bars(db_path, instrument="MNQ JUN26", timeframe="1m", start=240, end=300) == 1
    # Window itself is empty.
    assert _count_bars(db_path, instrument="MNQ JUN26", timeframe="1m", start=60, end=240) == 0


def test_delete_validates_payload(client):
    c, _db_path = client
    # Missing fields
    resp = c.post("/api/ohlc/bars/delete", json={})
    assert resp.status_code == 400
    # Non-int start
    resp = c.post(
        "/api/ohlc/bars/delete",
        json={"instrument": "MNQ", "timeframe": "1m", "start": "x", "end": 60},
    )
    assert resp.status_code == 400
    # Unknown timeframe
    resp = c.post(
        "/api/ohlc/bars/delete",
        json={"instrument": "MNQ", "timeframe": "2m", "start": 0, "end": 60},
    )
    assert resp.status_code == 400
    # start >= end
    resp = c.post(
        "/api/ohlc/bars/delete",
        json={"instrument": "MNQ", "timeframe": "1m", "start": 60, "end": 60},
    )
    assert resp.status_code == 400


def test_delete_no_rows_is_ok(client):
    c, _db_path = client
    resp = c.post(
        "/api/ohlc/bars/delete",
        json={"instrument": "NOPE", "timeframe": "1m", "start": 0, "end": 60},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "deleted": 0}
