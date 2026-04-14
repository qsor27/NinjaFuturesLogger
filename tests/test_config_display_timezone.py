import json
from pathlib import Path

from config import Config, load_config


def test_display_timezone_defaults_to_none(tmp_path: Path):
    raw = {
        "data_dir": "data",
        "db_path": "data/t.db",
        "inbox_dir": "data/inbox",
        "archive_dir": "data/archive",
        "log_dir": "data/logs",
        "session": {
            "exchange_timezone": "America/Chicago",
            "trade_date_rollover": "16:00",
            "archive_job_time": "18:00",
        },
        "thread_pool": {"max_workers": 4},
        "scheduler": {"heartbeat_seconds": 60},
    }
    p = tmp_path / "app.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.display_timezone is None


def test_display_timezone_loaded_when_present(tmp_path: Path):
    raw = {
        "data_dir": "data",
        "db_path": "data/t.db",
        "inbox_dir": "data/inbox",
        "archive_dir": "data/archive",
        "log_dir": "data/logs",
        "session": {
            "exchange_timezone": "America/Chicago",
            "trade_date_rollover": "16:00",
            "archive_job_time": "18:00",
        },
        "thread_pool": {"max_workers": 4},
        "scheduler": {"heartbeat_seconds": 60},
        "display_timezone": "Asia/Tokyo",
    }
    p = tmp_path / "app.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.display_timezone == "Asia/Tokyo"


def test_display_timezone_construct_directly():
    cfg = Config(
        data_dir="data",
        db_path="data/t.db",
        inbox_dir="data/inbox",
        archive_dir="data/archive",
        log_dir="data/logs",
        session={
            "exchange_timezone": "America/Chicago",
            "trade_date_rollover": "16:00",
            "archive_job_time": "18:00",
        },
        thread_pool={"max_workers": 4},
        scheduler={"heartbeat_seconds": 60},
    )
    assert cfg.display_timezone is None
