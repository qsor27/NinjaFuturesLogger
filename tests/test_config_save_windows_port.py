import json
from pathlib import Path

import pytest

from config import load_config, save_windows_port


def _seed_config(tmp_path: Path) -> Path:
    path = tmp_path / "app.json"
    path.write_text(
        json.dumps(
            {
                "data_dir": str(tmp_path),
                "db_path": str(tmp_path / "t.db"),
                "inbox_dir": str(tmp_path / "inbox"),
                "archive_dir": str(tmp_path / "archive"),
                "log_dir": str(tmp_path / "log"),
                "session": {
                    "exchange_timezone": "America/Chicago",
                    "trade_date_rollover": "17:00",
                    "archive_job_time": "18:00",
                },
                "thread_pool": {"max_workers": 4},
                "scheduler": {"heartbeat_seconds": 30},
            }
        )
    )
    return path


def test_save_windows_port_writes_value(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_windows_port(path, 8002)
    cfg = load_config(path)
    assert cfg.windows.port == 8002


def test_save_windows_port_preserves_other_fields(tmp_path: Path):
    path = _seed_config(tmp_path)
    before = json.loads(path.read_text())
    save_windows_port(path, 9123)
    after = json.loads(path.read_text())
    for k, v in before.items():
        assert after[k] == v, f"field {k} was mutated"
    assert after["windows"]["port"] == 9123


def test_save_windows_port_rejects_below_1024(tmp_path: Path):
    path = _seed_config(tmp_path)
    with pytest.raises(ValueError):
        save_windows_port(path, 80)


def test_save_windows_port_rejects_above_65535(tmp_path: Path):
    path = _seed_config(tmp_path)
    with pytest.raises(ValueError):
        save_windows_port(path, 70000)


def test_save_windows_port_rejects_non_int(tmp_path: Path):
    path = _seed_config(tmp_path)
    with pytest.raises(ValueError):
        save_windows_port(path, "8002")  # type: ignore[arg-type]


def test_save_windows_port_rejects_bool(tmp_path: Path):
    path = _seed_config(tmp_path)
    # Booleans are a subclass of int in Python; save_windows_port must reject them.
    with pytest.raises(ValueError):
        save_windows_port(path, True)  # type: ignore[arg-type]


def test_default_when_windows_section_missing(tmp_path: Path):
    path = _seed_config(tmp_path)
    cfg = load_config(path)
    assert cfg.windows.port == 8000  # default from WindowsConfig


def test_update_overwrites_existing_port(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_windows_port(path, 8002)
    save_windows_port(path, 9000)
    cfg = load_config(path)
    assert cfg.windows.port == 9000
