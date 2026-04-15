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
    config = load_config(app_json)
    app, _ = create_app(config)
    return app.test_client()


def test_get_instruments_returns_seeded(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.get("/api/config/instruments")
    assert res.status_code == 200
    body = res.get_json()
    assert "ES" in body["instruments"]
    assert body["instruments"]["ES"]["multiplier"] == 50.0


def test_put_instrument_round_trip(tmp_path: Path):
    client = _setup_app(tmp_path)
    payload = {
        "display_name": "Bitcoin",
        "multiplier": 5.0,
        "tick_size": 5.0,
        "sources": {
            "yfinance": {"continuous": "BTC=F", "contract_template": None},
            "stooq": {"continuous": None, "contract_template": None},
        },
        "session": {
            "timezone": "America/Chicago",
            "open": "17:00",
            "close": "16:00",
            "daily_break_start": "16:00",
            "daily_break_end": "17:00",
        },
    }
    res = client.put("/api/config/instruments/BTC", json=payload)
    assert res.status_code == 200
    body = res.get_json()
    assert body["instrument"]["multiplier"] == 5.0

    res = client.get("/api/config/instruments")
    assert "BTC" in res.get_json()["instruments"]


def test_put_instrument_rejects_invalid_payload(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.put("/api/config/instruments/FOO", json={"multiplier": "not-a-number"})
    assert res.status_code == 400


def test_delete_instrument(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.delete("/api/config/instruments/ES")
    assert res.status_code == 204
    res = client.get("/api/config/instruments")
    assert "ES" not in res.get_json()["instruments"]


def test_delete_unknown_instrument_404(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.delete("/api/config/instruments/BOGUS")
    assert res.status_code == 404


def test_put_instrument_persists_to_json_file(tmp_path: Path):
    client = _setup_app(tmp_path)
    payload = {
        "display_name": "X",
        "multiplier": 1.5,
        "tick_size": 0.01,
        "sources": {
            "yfinance": {"continuous": None, "contract_template": None},
            "stooq": {"continuous": None, "contract_template": None},
        },
        "session": {
            "timezone": "UTC",
            "open": "00:00",
            "close": "00:00",
            "daily_break_start": "",
            "daily_break_end": "",
        },
    }
    client.put("/api/config/instruments/XYZ", json=payload)
    json_path = tmp_path / "data" / "config" / "instruments.json"
    data = json.loads(json_path.read_text())
    assert data["XYZ"]["multiplier"] == 1.5


def test_settings_pages_return_200_and_reference_js(tmp_path: Path):
    client = _setup_app(tmp_path)
    for path, js in [
        ("/settings", None),
        ("/settings/instruments", "settings_instruments.js"),
        ("/settings/chart", "settings_chart.js"),
        ("/settings/custom-fields", "settings_custom_fields.js"),
    ]:
        res = client.get(path)
        assert res.status_code == 200
        if js is not None:
            assert js.encode() in res.data


def test_static_js_files_served(tmp_path: Path):
    client = _setup_app(tmp_path)
    for js in ("settings_instruments.js", "settings_chart.js", "settings_custom_fields.js"):
        res = client.get(f"/static/js/{js}")
        assert res.status_code == 200
