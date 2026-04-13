from services.instruments import (
    DEFAULT_TIMEFRAMES,
    default_session,
    source_symbol,
)


def test_default_timeframes_canonical():
    assert DEFAULT_TIMEFRAMES == ("1m", "5m", "15m", "1h", "1d")


def test_source_symbol_yfinance_known():
    assert source_symbol("MNQ", "yfinance") == "MNQ=F"
    assert source_symbol("ES", "yfinance") == "ES=F"


def test_source_symbol_stooq_known():
    assert source_symbol("MNQ", "stooq") == "mnq.f"
    assert source_symbol("ES", "stooq") == "es.f"


def test_source_symbol_strips_contract_suffix():
    assert source_symbol("MNQ SEP25", "yfinance") == "MNQ=F"


def test_source_symbol_unknown_returns_none():
    assert source_symbol("ZZZ", "yfinance") is None


def test_source_symbol_unknown_source_returns_none():
    assert source_symbol("MNQ", "polygon") is None


def test_default_session_shape():
    s = default_session("MNQ")
    assert s.timezone == "America/Chicago"
    assert s.open == "17:00"
    assert s.close == "16:00"
    assert s.daily_break_start == "16:00"
    assert s.daily_break_end == "17:00"
