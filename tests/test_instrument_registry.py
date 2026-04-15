import json
from pathlib import Path

import pytest

from services.instrument_registry import DEFAULT_SEED, InstrumentRegistry


def test_load_seeds_if_missing(tmp_path: Path):
    json_path = tmp_path / "instruments.json"
    reg = InstrumentRegistry(json_path)
    reg.load()
    assert json_path.exists()
    data = json.loads(json_path.read_text())
    assert "ES" in data
    assert data["ES"]["multiplier"] == 50.0
    assert data["ES"]["sources"]["yfinance"]["continuous"] == "ES=F"


def test_load_empty_file_reseeds(tmp_path: Path):
    json_path = tmp_path / "instruments.json"
    json_path.write_text("")
    reg = InstrumentRegistry(json_path)
    reg.load()
    data = json.loads(json_path.read_text())
    assert "ES" in data


def test_load_existing_file_not_overwritten(tmp_path: Path):
    json_path = tmp_path / "instruments.json"
    payload = {
        "ZZ": {
            "display_name": "Test",
            "multiplier": 99.0,
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
    }
    json_path.write_text(json.dumps(payload))
    reg = InstrumentRegistry(json_path)
    reg.load()
    assert reg.get("ZZ").multiplier == 99.0
    assert reg.get("ES") is None


def test_put_writes_file_atomically(tmp_path: Path, monkeypatch):
    json_path = tmp_path / "instruments.json"
    reg = InstrumentRegistry(json_path)
    reg.load()

    calls = []
    import os as _os

    original = _os.replace

    def tracking_replace(src, dst):
        calls.append((str(src), str(dst)))
        return original(src, dst)

    monkeypatch.setattr("os.replace", tracking_replace)

    from models.settings import (
        InstrumentConfig,
        InstrumentSession,
        InstrumentSources,
        SourceMapping,
    )

    cfg = InstrumentConfig(
        display_name="New",
        multiplier=7.0,
        tick_size=0.25,
        sources=InstrumentSources(
            yfinance=SourceMapping(continuous="NEW=F"),
            stooq=SourceMapping(),
        ),
        session=InstrumentSession(
            timezone="UTC",
            open="00:00",
            close="00:00",
            daily_break_start="",
            daily_break_end="",
        ),
    )
    reg.put("NEW", cfg)

    assert len(calls) == 1
    assert calls[0][1] == str(json_path)
    assert reg.get("NEW").multiplier == 7.0

    on_disk = json.loads(json_path.read_text())
    assert on_disk["NEW"]["multiplier"] == 7.0


def test_delete_removes_instrument(tmp_path: Path):
    json_path = tmp_path / "instruments.json"
    reg = InstrumentRegistry(json_path)
    reg.load()
    assert reg.get("ES") is not None
    reg.delete("ES")
    assert reg.get("ES") is None
    on_disk = json.loads(json_path.read_text())
    assert "ES" not in on_disk


def test_delete_unknown_raises(tmp_path: Path):
    reg = InstrumentRegistry(tmp_path / "instruments.json")
    reg.load()
    with pytest.raises(KeyError):
        reg.delete("NOPE")


def test_list_returns_sorted_symbols(tmp_path: Path):
    reg = InstrumentRegistry(tmp_path / "instruments.json")
    reg.load()
    symbols = [i[0] for i in reg.list()]
    assert symbols == sorted(symbols)


def test_concurrent_writers_serialize(tmp_path: Path):
    import threading

    json_path = tmp_path / "instruments.json"
    reg = InstrumentRegistry(json_path)
    reg.load()

    from models.settings import (
        InstrumentConfig,
        InstrumentSession,
        InstrumentSources,
        SourceMapping,
    )

    def _cfg(mult: float) -> InstrumentConfig:
        return InstrumentConfig(
            display_name="T",
            multiplier=mult,
            tick_size=0.25,
            sources=InstrumentSources(yfinance=SourceMapping(), stooq=SourceMapping()),
            session=InstrumentSession(
                timezone="UTC",
                open="00:00",
                close="00:00",
                daily_break_start="",
                daily_break_end="",
            ),
        )

    def worker(i: int):
        reg.put(f"T{i}", _cfg(float(i)))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(json_path.read_text())
    for i in range(20):
        assert f"T{i}" in data


def test_default_seed_covers_plan_11_multipliers():
    assert "ES" in DEFAULT_SEED
    assert DEFAULT_SEED["ES"]["multiplier"] == 50.0
    assert DEFAULT_SEED["MES"]["multiplier"] == 5.0
    assert DEFAULT_SEED["NQ"]["multiplier"] == 20.0
    assert DEFAULT_SEED["MNQ"]["multiplier"] == 2.0


def test_default_seed_covers_plan_14_symbol_maps():
    assert DEFAULT_SEED["ES"]["sources"]["yfinance"]["continuous"] == "ES=F"
    assert DEFAULT_SEED["ES"]["sources"]["stooq"]["continuous"] == "es.f"
    assert DEFAULT_SEED["6E"]["sources"]["yfinance"]["continuous"] == "6E=F"
