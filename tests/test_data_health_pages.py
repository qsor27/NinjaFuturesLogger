"""Render-smoke tests for the two Data Health tab pages.

These don't exercise JS — they just confirm the routes return 200, the
right template is loaded, and the shared header macro renders with the
correct active tab.
"""

import pytest

from app import create_app


@pytest.fixture
def client(tmp_config):
    app, _services = create_app(tmp_config, start_background=False)
    with app.test_client() as c:
        yield c


def test_data_health_coverage_page_renders(client):
    resp = client.get("/data-health")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Do I have the data I need?" in html
    assert 'id="completeness-matrix"' in html
    assert 'id="gaps-panel"' in html
    # Shared header macro
    assert 'id="verdict-banner"' in html
    # Tabs
    assert 'href="/data-health"' in html
    assert 'href="/data-health/system"' in html
    # Old 4h notice removed
    assert "4h candles are derived" not in html
    # Correct JS modules loaded, old module not loaded
    assert "data_health_verdict.js" in html
    assert "data_health_coverage.js" in html
    assert "data_health_system.js" not in html


def test_data_health_system_page_renders(client):
    resp = client.get("/data-health/system")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Is the data pipeline healthy?" in html
    assert 'id="sources-band"' in html
    assert 'id="maintainer-panel"' in html
    assert 'id="attempts-panel"' in html
    assert 'id="verdict-banner"' in html
    assert "data_health_verdict.js" in html
    assert "data_health_system.js" in html
    assert "data_health_coverage.js" not in html
