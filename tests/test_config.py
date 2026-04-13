import json
from pathlib import Path

from config import Config, load_config


def test_load_config_reads_json(tmp_path: Path):
    cfg_file = tmp_path / "app.json"
    cfg_file.write_text(json.dumps({
        "data_dir": "data",
        "db_path": "data/trading_log.db",
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
    }))
    cfg = load_config(cfg_file)
    assert isinstance(cfg, Config)
    assert cfg.thread_pool.max_workers == 4
    assert cfg.session.exchange_timezone == "America/Chicago"


def test_load_config_rejects_unknown_field(tmp_path: Path):
    cfg_file = tmp_path / "app.json"
    cfg_file.write_text(json.dumps({"data_dir": "data", "bogus": 1}))
    try:
        load_config(cfg_file)
    except Exception:
        return
    raise AssertionError("expected validation error for 'bogus'")
