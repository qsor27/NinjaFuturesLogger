from app import create_app


def test_healthz_returns_unhealthy_with_services_stopped(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["sqlite"] is True
    assert body["scheduler"] is False
    assert body["watchdog"] is False


def test_healthz_returns_ok_with_services_started(tmp_config):
    app, services = create_app(tmp_config, start_background=True)
    services._heartbeat()
    try:
        client = app.test_client()
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["sqlite"] is True
        assert body["scheduler"] is True
        assert body["watchdog"] is True
        assert body["pool_saturated"] is False
    finally:
        services.stop()
