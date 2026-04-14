from app import create_app


def test_plan12_blueprints_registered(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        names = set(app.blueprints.keys())
        assert "user_metadata" in names
        assert "links" in names
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


def test_link_group_lifecycle_end_to_end(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        client = app.test_client()
        create = client.post(
            "/api/links",
            json={
                "label": "e2e",
                "members": [
                    {"account": "A", "instrument": "MNQ", "entry_execution_id": "e1"}
                ],
            },
        )
        assert create.status_code == 201
        gid = create.get_json()["link_group_id"]
        detail = client.get(f"/api/links/{gid}")
        assert detail.status_code == 200
        assert detail.get_json()["label"] == "e2e"
        page = client.get(f"/links/{gid}")
        assert page.status_code == 200
        assert f'data-link-group-id="{gid}"' in page.get_data(as_text=True)
        client.delete(f"/api/links/{gid}")
        assert client.get(f"/api/links/{gid}").status_code == 404
    finally:
        services.stop()
