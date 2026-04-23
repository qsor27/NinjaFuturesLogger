import pytest

from app import create_app


@pytest.fixture
def client(tmp_config):
    app, _services = create_app(tmp_config, start_background=False)
    with app.test_client() as c:
        yield c, tmp_config.db_path


def test_summary_healthy_when_no_gaps_no_open_sources(client):
    c, _db_path = client
    resp = c.get("/api/data-health/summary")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["verdict"] == "healthy"
    assert body["word"] == "Healthy"
    assert body["open_sources_count"] == 0
    assert body["open_gaps_count"] == 0
    assert "responding" in body["line"].lower()


def test_summary_attention_when_gaps_but_no_open_sources(client):
    c, db_path = client
    from db import connect

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO ohlc_gap_reports"
        " (instrument, timeframe, gap_start, gap_end, first_seen_at,"
        "  attempt_count, next_retry_at, state)"
        " VALUES ('MNQ', '1m', 0, 60, 1000, 0, 2000, 'open')"
    )
    conn.close()
    resp = c.get("/api/data-health/summary")
    body = resp.get_json()
    assert body["verdict"] == "attention"
    assert body["open_gaps_count"] == 1
    assert body["next_retry_at"] == 2000


def test_summary_degraded_when_any_source_open(client, tmp_config):
    c, db_path = client
    # Persist an open breaker state, then reload via the registry API.
    from db import connect

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO ohlc_breaker_state"
        " (source, state, consecutive_failures, consecutive_trips,"
        "  current_cooldown_seconds, opened_at, next_retry_at, updated_at)"
        " VALUES ('yfinance', 'open', 3, 1, 300, 100, 400, 100)"
    )
    conn.close()
    # We need the registry to reflect the open state; easiest is to reload breaker
    # from DB via load_breaker directly on the registry the app wired up.
    from services.ohlc.breaker_persistence import load_breaker

    with c.application.app_context():
        registry = c.application.config["FTL_OHLC_REGISTRY"]
        conn2 = connect(db_path)
        try:
            for _s, breaker in registry.entries:
                load_breaker(conn2, breaker)
        finally:
            conn2.close()
    resp = c.get("/api/data-health/summary")
    body = resp.get_json()
    assert body["verdict"] == "degraded"
    assert body["open_sources_count"] >= 1
    assert "tripped" in body["line"]
