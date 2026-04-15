from app import create_app


def test_plan12_blueprints_registered(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        names = set(app.blueprints.keys())
        assert "user_metadata" in names
        assert "pages" in names
    finally:
        services.stop()


def test_positions_page_and_api_both_reachable(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        client = app.test_client()
        html = client.get("/positions")
        assert html.status_code == 200
        assert html.content_type.startswith("text/html")
        api = client.get("/api/positions")
        assert api.status_code == 200
        assert api.content_type.startswith("application/json")
    finally:
        services.stop()
