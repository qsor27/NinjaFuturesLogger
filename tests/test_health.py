def test_healthz_returns_unhealthy_with_services_stopped(app_and_services):
    app, services = app_and_services
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["sqlite"] is True
    assert body["scheduler"] is False
    assert body["watchdog"] is False


def test_healthz_returns_ok_with_services_started(started_app_and_services):
    app, services = started_app_and_services
    services._heartbeat()
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["sqlite"] is True
    assert body["scheduler"] is True
    assert body["watchdog"] is True
    assert body["pool_saturated"] is False
