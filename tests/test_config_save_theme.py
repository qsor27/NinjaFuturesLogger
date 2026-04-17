import json
import threading
from pathlib import Path

import pytest

from config import load_config, save_theme


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


def test_save_theme_writes_light(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_theme(path, "light")
    cfg = load_config(path)
    assert cfg.theme == "light"


def test_save_theme_writes_dark(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_theme(path, "light")
    save_theme(path, "dark")
    cfg = load_config(path)
    assert cfg.theme == "dark"


def test_save_theme_preserves_other_fields(tmp_path: Path):
    path = _seed_config(tmp_path)
    before = json.loads(path.read_text())
    save_theme(path, "light")
    after = json.loads(path.read_text())
    for k, v in before.items():
        assert after[k] == v, f"field {k} was mutated"


def test_save_theme_rejects_invalid(tmp_path: Path):
    path = _seed_config(tmp_path)
    with pytest.raises(ValueError):
        save_theme(path, "purple")


def test_save_theme_rejects_none(tmp_path: Path):
    path = _seed_config(tmp_path)
    with pytest.raises(ValueError):
        save_theme(path, None)  # type: ignore[arg-type]


def test_save_theme_leaves_no_tmp_file(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_theme(path, "light")
    assert not (tmp_path / "app.json.tmp").exists()


def test_save_theme_thread_safe(tmp_path: Path):
    path = _seed_config(tmp_path)
    errors: list[Exception] = []

    def worker(value: str):
        try:
            save_theme(path, value)
        except Exception as e:
            errors.append(e)

    values = ["dark", "light"]
    threads = [threading.Thread(target=worker, args=(v,)) for v in values * 10]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    cfg = load_config(path)
    assert cfg.theme in values
