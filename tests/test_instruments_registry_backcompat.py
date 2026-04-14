"""Pin the public surface of services/instruments.py through plan 16's body
swap. Plan 11 callers (positions.py), plan 14 callers (ohlc sources,
gap_detection, app.py hook) must see identical results for known seed
instruments after the InstrumentRegistry replaces the hardcoded tables."""

from pathlib import Path

import services.instruments as instruments
from services.instrument_registry import InstrumentRegistry


def _with_registry(tmp_path: Path, monkeypatch):
    reg = InstrumentRegistry(tmp_path / "instruments.json")
    reg.load()
    monkeypatch.setattr(instruments, "_REGISTRY", reg)


def test_get_multiplier_known(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.get_multiplier("ES") == 50.0
    assert instruments.get_multiplier("MES") == 5.0
    assert instruments.get_multiplier("NQ") == 20.0
    assert instruments.get_multiplier("MNQ") == 2.0


def test_get_multiplier_with_contract_suffix(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.get_multiplier("ES SEP25") == 50.0


def test_get_multiplier_unknown_returns_one(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.get_multiplier("BOGUS") == 1.0


def test_source_symbol_yfinance(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.source_symbol("ES", "yfinance") == "ES=F"
    assert instruments.source_symbol("MES", "yfinance") == "MES=F"


def test_source_symbol_stooq(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.source_symbol("ES", "stooq") == "es.f"


def test_source_symbol_unknown_source(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.source_symbol("ES", "bogus") is None


def test_source_symbol_unknown_instrument(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.source_symbol("ZZZ", "yfinance") is None


def test_default_timeframes_preserved():
    assert instruments.DEFAULT_TIMEFRAMES == ("1m", "5m", "15m", "1h", "1d")


def test_default_session_returns_cme_default(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    session = instruments.default_session("ES")
    assert session.timezone == "America/Chicago"
    assert session.open == "17:00"
    assert session.close == "16:00"
    assert session.daily_break_start == "16:00"
    assert session.daily_break_end == "17:00"


def test_base_symbol_strips_contract(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.base_symbol("ES SEP25") == "ES"
    assert instruments.base_symbol("MNQ") == "MNQ"


def test_edit_registry_changes_multiplier(tmp_path: Path, monkeypatch):
    reg = InstrumentRegistry(tmp_path / "instruments.json")
    reg.load()
    monkeypatch.setattr(instruments, "_REGISTRY", reg)

    from models.settings import (
        InstrumentConfig,
        InstrumentSession,
        InstrumentSources,
        SourceMapping,
    )

    reg.put(
        "ES",
        InstrumentConfig(
            display_name="E-mini S&P 500",
            multiplier=25.0,
            tick_size=0.25,
            sources=InstrumentSources(
                yfinance=SourceMapping(continuous="ES=F"),
                stooq=SourceMapping(continuous="es.f"),
            ),
            session=InstrumentSession(
                timezone="America/Chicago",
                open="17:00", close="16:00",
                daily_break_start="16:00", daily_break_end="17:00",
            ),
        ),
    )
    assert instruments.get_multiplier("ES") == 25.0
