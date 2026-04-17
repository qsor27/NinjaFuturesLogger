import json
from pathlib import Path

from app import create_app
from config import load_config


def _setup_app(tmp_path: Path):
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "archive").mkdir()
    (data_dir / "log").mkdir()
    app_json = data_dir / "config" / "app.json"
    app_json.write_text(
        json.dumps(
            {
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
            }
        )
    )
    return create_app(load_config(app_json))[0].test_client(), app_json


def test_put_theme_light_persists(tmp_path: Path):
    client, app_json = _setup_app(tmp_path)
    res = client.put("/api/config/theme", json={"theme": "light"})
    assert res.status_code == 200
    assert res.get_json() == {"theme": "light"}
    assert json.loads(app_json.read_text())["theme"] == "light"


def test_put_theme_dark_round_trip(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    client.put("/api/config/theme", json={"theme": "light"})
    res = client.put("/api/config/theme", json={"theme": "dark"})
    assert res.status_code == 200
    assert res.get_json() == {"theme": "dark"}


def test_put_theme_invalid_returns_400(tmp_path: Path):
    client, app_json = _setup_app(tmp_path)
    before = app_json.read_text()
    res = client.put("/api/config/theme", json={"theme": "purple"})
    assert res.status_code == 400
    # app.json must be unchanged on error
    assert app_json.read_text() == before


def test_put_theme_missing_key_returns_400(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.put("/api/config/theme", json={})
    assert res.status_code == 400


def test_put_theme_reloads_app_config(tmp_path: Path):
    """Context processor must reflect the new value on the next request."""
    client, _ = _setup_app(tmp_path)
    client.put("/api/config/theme", json={"theme": "light"})
    res = client.get("/settings")
    assert res.status_code == 200
    assert b'data-theme="light"' in res.data


def test_settings_index_renders_data_theme_default_dark(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.get("/settings")
    assert res.status_code == 200
    assert b'data-theme="dark"' in res.data
