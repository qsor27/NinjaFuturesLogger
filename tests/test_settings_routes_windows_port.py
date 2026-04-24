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


def test_get_windows_port_returns_default(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.get("/api/settings/windows-port")
    assert res.status_code == 200
    assert res.get_json() == {"port": 8000}


def test_put_windows_port_persists(tmp_path: Path):
    client, app_json = _setup_app(tmp_path)
    res = client.put("/api/settings/windows-port", json={"port": 8002})
    assert res.status_code == 200
    body = res.get_json()
    assert body["port"] == 8002
    assert body["restart_required"] is True
    assert json.loads(app_json.read_text())["windows"]["port"] == 8002


def test_put_windows_port_reflects_in_get(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    client.put("/api/settings/windows-port", json={"port": 9000})
    res = client.get("/api/settings/windows-port")
    assert res.get_json() == {"port": 9000}


def test_put_rejects_below_1024(tmp_path: Path):
    client, app_json = _setup_app(tmp_path)
    before = app_json.read_text()
    res = client.put("/api/settings/windows-port", json={"port": 80})
    assert res.status_code == 400
    assert app_json.read_text() == before


def test_put_rejects_above_65535(tmp_path: Path):
    client, app_json = _setup_app(tmp_path)
    before = app_json.read_text()
    res = client.put("/api/settings/windows-port", json={"port": 70000})
    assert res.status_code == 400
    assert app_json.read_text() == before


def test_put_rejects_non_integer(tmp_path: Path):
    client, app_json = _setup_app(tmp_path)
    before = app_json.read_text()
    res = client.put("/api/settings/windows-port", json={"port": "8002"})
    assert res.status_code == 400
    assert app_json.read_text() == before


def test_put_rejects_boolean(tmp_path: Path):
    client, app_json = _setup_app(tmp_path)
    before = app_json.read_text()
    res = client.put("/api/settings/windows-port", json={"port": True})
    assert res.status_code == 400
    assert app_json.read_text() == before


def test_put_rejects_missing_body(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.put("/api/settings/windows-port", json={})
    assert res.status_code == 400
