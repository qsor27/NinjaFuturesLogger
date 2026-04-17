import json
from pathlib import Path

from app import create_app
from config import load_config


def _setup_app(tmp_path: Path, theme: str | None = None):
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "archive").mkdir()
    (data_dir / "log").mkdir()
    app_json = data_dir / "config" / "app.json"
    payload = {
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
    if theme is not None:
        payload["theme"] = theme
    app_json.write_text(json.dumps(payload))
    return create_app(load_config(app_json))[0]


def test_context_processor_exposes_theme_default_dark(tmp_path: Path):
    app = _setup_app(tmp_path)
    with app.test_request_context("/"):
        from flask import render_template_string
        out = render_template_string("{{ theme }}")
    assert out == "dark"


def test_context_processor_exposes_theme_light(tmp_path: Path):
    app = _setup_app(tmp_path, theme="light")
    with app.test_request_context("/"):
        from flask import render_template_string
        out = render_template_string("{{ theme }}")
    assert out == "light"
