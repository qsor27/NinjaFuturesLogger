def test_all_stats_routes_are_wired(app):
    client = app.test_client()
    for path in [
        "/api/stats/summary",
        "/api/stats/by-instrument",
        "/api/stats/by-day",
        "/api/stats/by-week",
        "/api/stats/by-month",
        "/api/stats/by-hour",
        "/api/stats/by-side",
        "/api/stats/by-day-of-week",
        "/api/stats/equity-curve",
        "/api/stats/distribution",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"


def test_statistics_page_renders(app):
    resp = app.test_client().get("/statistics")
    assert resp.status_code == 200
    assert b"stats-root" in resp.data
    assert b"stats.css" in resp.data
    assert b"statistics.js" in resp.data
    assert b"lightweight-charts.standalone.production.js" in resp.data


def test_calendar_page_renders(app):
    resp = app.test_client().get("/calendar")
    assert resp.status_code == 200
    assert b"calendar-root" in resp.data
    assert b"calendar.js" in resp.data


def test_static_stats_assets_are_served(app):
    client = app.test_client()
    for path, sentinel in [
        ("/static/css/stats.css", b"--bg-page"),
        ("/static/js/stats_filter.js", b"parseFilterFromUrl"),
        ("/static/js/stats_charts.js", b"mountCalendarHeatmap"),
        ("/static/js/statistics.js", b"renderSummary"),
        ("/static/js/calendar.js", b"isoWeekToDate"),
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
        assert sentinel in resp.data, f"{path} missing sentinel {sentinel!r}"


def test_simulations_page_renders(app):
    resp = app.test_client().get("/simulations")
    assert resp.status_code == 200
    for sentinel in (
        b"sim-root",
        b"sim-rules",
        b"sim-results",
        b"simulations.css",
        b"simulations.js",
    ):
        assert sentinel in resp.data, sentinel
    assert b"lightweight-charts.standalone.production.js" in resp.data


def test_nav_links_to_simulations(app):
    resp = app.test_client().get("/statistics")
    assert b'href="/simulations"' in resp.data
