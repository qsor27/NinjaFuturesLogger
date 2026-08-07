def test_positions_list_page_renders_shell(client):
    resp = client.get("/positions")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "<h1>Positions</h1>" in html
    assert 'id="filter-form"' in html
    assert 'id="list-root"' in html
    assert 'src="/static/js/positions_list.js"' in html


def test_position_detail_page_renders_with_data_attrs(client):
    resp = client.get("/positions/Sim101/MNQ/abc123")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'data-account="Sim101"' in html
    assert 'data-instrument="MNQ"' in html
    assert 'data-entry-execution-id="abc123"' in html
    assert 'id="detail-root"' in html
    assert 'id="chart-root"' in html
    assert 'src="/static/js/position_detail.js"' in html
