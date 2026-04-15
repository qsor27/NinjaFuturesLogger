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


def test_get_chart_defaults_returns_seed(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.get("/api/config/chart-defaults")
    assert res.status_code == 200
    body = res.get_json()
    assert body["default_timeframe"] == "5m"
    assert body["volume_visible_default"] is True
    assert body["display_timezone"] is None


def test_put_chart_defaults_round_trip(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.put(
        "/api/config/chart-defaults",
        json={
            "default_timeframe": "1m",
            "volume_visible_default": False,
            "display_timezone": "Asia/Tokyo",
        },
    )
    assert res.status_code == 200
    res = client.get("/api/config/chart-defaults")
    body = res.get_json()
    assert body["default_timeframe"] == "1m"
    assert body["volume_visible_default"] is False
    assert body["display_timezone"] == "Asia/Tokyo"


def test_put_chart_defaults_rejects_invalid_timeframe(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.put(
        "/api/config/chart-defaults",
        json={
            "default_timeframe": "2m",
            "volume_visible_default": True,
            "display_timezone": None,
        },
    )
    assert res.status_code == 400


def test_put_chart_defaults_rejects_invalid_timezone(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.put(
        "/api/config/chart-defaults",
        json={
            "default_timeframe": "5m",
            "volume_visible_default": True,
            "display_timezone": "Not/A_Timezone",
        },
    )
    assert res.status_code == 400


def test_put_chart_defaults_persists_display_timezone_to_app_json(tmp_path: Path):
    client, app_json = _setup_app(tmp_path)
    client.put(
        "/api/config/chart-defaults",
        json={
            "default_timeframe": "5m",
            "volume_visible_default": True,
            "display_timezone": "Europe/London",
        },
    )
    data = json.loads(app_json.read_text())
    assert data["display_timezone"] == "Europe/London"
