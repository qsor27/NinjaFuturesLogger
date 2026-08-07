import json
import threading
from pathlib import Path

import pytest

from config import load_config, save_display_timezone
from tests.conftest import seed_app_json


def test_save_display_timezone_writes_field(tmp_path: Path):
    path = seed_app_json(tmp_path)
    save_display_timezone(path, "Asia/Tokyo")
    cfg = load_config(path)
    assert cfg.display_timezone == "Asia/Tokyo"


def test_save_display_timezone_preserves_other_fields(tmp_path: Path):
    path = seed_app_json(tmp_path)
    before = json.loads(path.read_text())
    save_display_timezone(path, "Europe/London")
    after = json.loads(path.read_text())
    for k, v in before.items():
        assert after[k] == v


def test_save_display_timezone_rejects_invalid_iana(tmp_path: Path):
    path = seed_app_json(tmp_path)
    with pytest.raises(ValueError):
        save_display_timezone(path, "Not/A_Timezone")


def test_save_display_timezone_accepts_none(tmp_path: Path):
    path = seed_app_json(tmp_path)
    save_display_timezone(path, None)
    cfg = load_config(path)
    assert cfg.display_timezone is None


def test_save_display_timezone_thread_safe(tmp_path: Path):
    path = seed_app_json(tmp_path)
    errors = []

    def worker(tz: str):
        try:
            save_display_timezone(path, tz)
        except Exception as e:
            errors.append(e)

    tzs = ["Asia/Tokyo", "Europe/London", "America/New_York", "America/Chicago"]
    threads = [threading.Thread(target=worker, args=(tz,)) for tz in tzs * 5]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    cfg = load_config(path)
    assert cfg.display_timezone in tzs
