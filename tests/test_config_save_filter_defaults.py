import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from config import (
    Config,
    FilterDefaults,
    PositionsFilterDefault,
    StatsFilterDefault,
    load_config,
)


def _seed_config(tmp_path: Path, extra: dict | None = None) -> Path:
    """Seed a minimal app.json in tmp_path. `extra` is merged at the top level."""
    body = {
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
    if extra:
        body.update(extra)
    path = tmp_path / "app.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_config_without_filter_defaults_loads_cleanly(tmp_path: Path):
    path = _seed_config(tmp_path)
    cfg = load_config(path)
    assert cfg.filter_defaults == FilterDefaults()
    assert cfg.filter_defaults.positions is None
    assert cfg.filter_defaults.stats is None


def test_config_with_filter_defaults_round_trips(tmp_path: Path):
    path = _seed_config(
        tmp_path,
        {
            "filter_defaults": {
                "positions": {
                    "accounts": ["Sim101"],
                    "instrument": "MNQ",
                    "side": "Long",
                    "outcome": "",
                },
                "stats": {"accounts": ["Sim101"], "side": ""},
            }
        },
    )
    cfg = load_config(path)
    assert cfg.filter_defaults.positions == PositionsFilterDefault(
        accounts=("Sim101",), instrument="MNQ", side="Long", outcome=""
    )
    assert cfg.filter_defaults.stats == StatsFilterDefault(
        accounts=("Sim101",), side=""
    )


def test_positions_filter_default_rejects_unknown_key():
    with pytest.raises(ValidationError):
        PositionsFilterDefault(accounts=(), instrument="", side="", outcome="", evil="x")  # type: ignore[call-arg]


from config import save_filter_default


def test_save_filter_default_writes_positions(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_filter_default(
        path,
        "positions",
        {"accounts": ["Sim101"], "instrument": "MNQ", "side": "Long", "outcome": ""},
    )
    cfg = load_config(path)
    assert cfg.filter_defaults.positions == PositionsFilterDefault(
        accounts=("Sim101",), instrument="MNQ", side="Long", outcome=""
    )
    assert cfg.filter_defaults.stats is None


def test_save_filter_default_writes_stats(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_filter_default(
        path,
        "stats",
        {"accounts": ["A", "B"], "side": "Short"},
    )
    cfg = load_config(path)
    assert cfg.filter_defaults.stats == StatsFilterDefault(
        accounts=("A", "B"), side="Short"
    )


def test_save_filter_default_none_clears_scope(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_filter_default(path, "positions", {"accounts": ["A"]})
    save_filter_default(path, "positions", None)
    cfg = load_config(path)
    assert cfg.filter_defaults.positions is None


def test_save_filter_default_none_on_absent_scope_is_ok(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_filter_default(path, "stats", None)
    cfg = load_config(path)
    assert cfg.filter_defaults.stats is None


def test_save_filter_default_rejects_bad_scope(tmp_path: Path):
    path = _seed_config(tmp_path)
    with pytest.raises(ValueError):
        save_filter_default(path, "bogus", {"accounts": []})


def test_save_filter_default_rejects_unknown_body_key(tmp_path: Path):
    path = _seed_config(tmp_path)
    with pytest.raises(ValidationError):
        save_filter_default(path, "positions", {"accounts": [], "evil": "x"})


def test_save_filter_default_preserves_other_fields(tmp_path: Path):
    path = _seed_config(tmp_path)
    before = json.loads(path.read_text())
    save_filter_default(path, "positions", {"accounts": ["A"]})
    after = json.loads(path.read_text())
    for k, v in before.items():
        assert after[k] == v, f"field {k} was mutated"


def test_save_filter_default_leaves_no_tmp_file(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_filter_default(path, "positions", {"accounts": ["A"]})
    assert not (tmp_path / "app.json.tmp").exists()


def test_save_filter_default_thread_safe(tmp_path: Path):
    import threading as _threading

    path = _seed_config(tmp_path)
    errors: list[Exception] = []

    def worker(accounts: list[str]):
        try:
            save_filter_default(path, "positions", {"accounts": accounts})
        except Exception as e:
            errors.append(e)

    threads = [
        _threading.Thread(target=worker, args=([f"A{i}"],)) for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    cfg = load_config(path)
    assert cfg.filter_defaults.positions is not None
