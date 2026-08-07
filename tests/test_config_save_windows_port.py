import json
from pathlib import Path

import pytest

from config import load_config, save_windows_port
from tests.conftest import seed_app_json


def test_save_windows_port_writes_value(tmp_path: Path):
    path = seed_app_json(tmp_path)
    save_windows_port(path, 8002)
    cfg = load_config(path)
    assert cfg.windows.port == 8002


def test_save_windows_port_preserves_other_fields(tmp_path: Path):
    path = seed_app_json(tmp_path)
    before = json.loads(path.read_text())
    save_windows_port(path, 9123)
    after = json.loads(path.read_text())
    for k, v in before.items():
        assert after[k] == v, f"field {k} was mutated"
    assert after["windows"]["port"] == 9123


@pytest.mark.parametrize("bad", [80, 70000, "8002", True])
def test_save_windows_port_rejects_invalid(tmp_path: Path, bad):
    # Booleans are a subclass of int in Python; save_windows_port must reject them.
    path = seed_app_json(tmp_path)
    with pytest.raises(ValueError):
        save_windows_port(path, bad)  # type: ignore[arg-type]


def test_default_when_windows_section_missing(tmp_path: Path):
    path = seed_app_json(tmp_path)
    cfg = load_config(path)
    assert cfg.windows.port == 8000  # default from WindowsConfig


def test_update_overwrites_existing_port(tmp_path: Path):
    path = seed_app_json(tmp_path)
    save_windows_port(path, 8002)
    save_windows_port(path, 9000)
    cfg = load_config(path)
    assert cfg.windows.port == 9000
