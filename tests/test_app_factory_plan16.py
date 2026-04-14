import json
from pathlib import Path

from app import create_app
from config import load_config


def _setup(tmp_path: Path):
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "archive").mkdir()
    (data_dir / "log").mkdir()
    app_json = data_dir / "config" / "app.json"
    app_json.write_text(json.dumps({
        "data_dir": str(data_dir),
        "db_path": str(data_dir / "ftl.db"),
        "inbox_dir": str(data_dir / "inbox"),
        "archive_dir": str(data_dir / "archive"),
        "log_dir": str(data_dir / "log"),
        "session": {
            "exchange_timezone": "America/Chicago",
            "trade_date_rollover": "17:00",
            "archive_job_time": "18:00",
        },
        "thread_pool": {"max_workers": 2},
        "scheduler": {"heartbeat_seconds": 30},
    }))
    return create_app(load_config(app_json))[0].test_client()


EXPECTED_API_ROUTES = [
    ("/api/config/instruments", "GET"),
    ("/api/config/chart-defaults", "GET"),
    ("/api/custom-fields", "GET"),
]

EXPECTED_PAGE_ROUTES = [
    "/settings",
    "/settings/instruments",
    "/settings/chart",
    "/settings/custom-fields",
]

EXPECTED_STATIC = [
    "/static/js/settings_instruments.js",
    "/static/js/settings_chart.js",
    "/static/js/settings_custom_fields.js",
    "/static/js/custom_fields_detail.js",
    "/static/css/settings.css",
]


def test_api_routes_wired(tmp_path: Path):
    client = _setup(tmp_path)
    for path, method in EXPECTED_API_ROUTES:
        res = client.open(path, method=method)
        assert res.status_code in (200, 204), f"{method} {path} => {res.status_code}"


def test_page_routes_wired(tmp_path: Path):
    client = _setup(tmp_path)
    for path in EXPECTED_PAGE_ROUTES:
        res = client.get(path)
        assert res.status_code == 200, f"GET {path} => {res.status_code}"


def test_static_assets_served(tmp_path: Path):
    client = _setup(tmp_path)
    for path in EXPECTED_STATIC:
        res = client.get(path)
        assert res.status_code == 200, f"GET {path} => {res.status_code}"


def test_instruments_json_created_on_startup(tmp_path: Path):
    _setup(tmp_path)
    instruments_json = tmp_path / "data" / "config" / "instruments.json"
    assert instruments_json.exists()
    data = json.loads(instruments_json.read_text())
    assert "ES" in data
