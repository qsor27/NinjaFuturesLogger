from app import create_app


def test_positions_list_page_renders_shell(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/positions")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "<h1>Positions</h1>" in html
        assert 'id="filter-form"' in html
        assert 'id="list-root"' in html
        assert 'src="/static/js/positions_list.js"' in html
    finally:
        services.stop()


def test_position_detail_page_renders_with_data_attrs(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/positions/Sim101/MNQ/abc123")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-account="Sim101"' in html
        assert 'data-instrument="MNQ"' in html
        assert 'data-entry-execution-id="abc123"' in html
        assert 'id="detail-root"' in html
        assert 'id="chart-root"' in html
        assert 'src="/static/js/position_detail.js"' in html
    finally:
        services.stop()


def test_link_group_page_renders_with_id(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/links/42")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-link-group-id="42"' in html
        assert 'id="link-root"' in html
        assert 'src="/static/js/link_group.js"' in html
    finally:
        services.stop()


def test_links_index_redirects_or_renders_positions(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/links")
        assert resp.status_code in (200, 302)
    finally:
        services.stop()
