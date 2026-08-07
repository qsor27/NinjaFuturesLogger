import json
import threading
from pathlib import Path

import pytest

from config import load_config, save_theme
from tests.conftest import seed_app_json


def test_save_theme_writes_light(tmp_path: Path):
    path = seed_app_json(tmp_path)
    save_theme(path, "light")
    cfg = load_config(path)
    assert cfg.theme == "light"


def test_save_theme_writes_dark(tmp_path: Path):
    path = seed_app_json(tmp_path)
    save_theme(path, "light")
    save_theme(path, "dark")
    cfg = load_config(path)
    assert cfg.theme == "dark"


def test_save_theme_preserves_other_fields(tmp_path: Path):
    path = seed_app_json(tmp_path)
    before = json.loads(path.read_text())
    save_theme(path, "light")
    after = json.loads(path.read_text())
    for k, v in before.items():
        assert after[k] == v, f"field {k} was mutated"


def test_save_theme_rejects_invalid(tmp_path: Path):
    path = seed_app_json(tmp_path)
    with pytest.raises(ValueError):
        save_theme(path, "purple")


def test_save_theme_rejects_none(tmp_path: Path):
    path = seed_app_json(tmp_path)
    with pytest.raises(ValueError):
        save_theme(path, None)  # type: ignore[arg-type]


def test_save_theme_leaves_no_tmp_file(tmp_path: Path):
    path = seed_app_json(tmp_path)
    save_theme(path, "light")
    assert not (tmp_path / "app.json.tmp").exists()


def test_save_theme_thread_safe(tmp_path: Path):
    path = seed_app_json(tmp_path)
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
