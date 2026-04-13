import pytest

from models.bar import Bar
from services.ohlc import stooq_source as ss
from services.ohlc.stooq_source import StooqSource

_DAILY_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-04-10,4200.00,4250.00,4180.00,4230.50,123456\n"
    "2026-04-11,4231.00,4240.00,4180.00,4189.00,98765\n"
)


def test_name_is_stooq():
    assert StooqSource().name == "stooq"


def test_supported_timeframes_is_daily_only():
    assert StooqSource().supported_timeframes == frozenset({"1d"})


def test_fetch_unknown_instrument_returns_empty():
    assert StooqSource().fetch("ZZZ_NOT_REAL", "1d", 1, 2) == []


def test_fetch_unsupported_timeframe_returns_empty():
    assert StooqSource().fetch("MNQ", "1m", 1, 2) == []


def test_fetch_parses_daily_csv(monkeypatch):
    captured = {}

    def fake_get(url):
        captured["url"] = url
        return _DAILY_CSV

    monkeypatch.setattr(ss, "_http_get", fake_get)

    start = ss._iso_to_unix("2026-04-09")
    end = ss._iso_to_unix("2026-04-12")
    bars = StooqSource().fetch("MNQ", "1d", start, end)

    assert "mnq.f" in captured["url"]
    assert "i=d" in captured["url"]
    assert len(bars) == 2
    assert all(isinstance(b, Bar) for b in bars)
    assert all(b.source == "stooq" for b in bars)
    assert all(b.instrument == "MNQ" for b in bars)
    assert all(b.timeframe == "1d" for b in bars)
    assert bars[0].close == 4230.50
    assert bars[1].close == 4189.00


def test_fetch_filters_to_requested_range(monkeypatch):
    monkeypatch.setattr(ss, "_http_get", lambda url: _DAILY_CSV)
    start = ss._iso_to_unix("2026-04-11")
    end = ss._iso_to_unix("2026-04-12")
    bars = StooqSource().fetch("MNQ", "1d", start, end)
    assert len(bars) == 1
    assert bars[0].close == 4189.00


def test_fetch_blank_volume_becomes_zero(monkeypatch):
    csv_text = "Date,Open,High,Low,Close,Volume\n" "2026-04-10,4200.00,4250.00,4180.00,4230.50,\n"
    monkeypatch.setattr(ss, "_http_get", lambda url: csv_text)
    bars = StooqSource().fetch("MNQ", "1d", 0, 9_999_999_999)
    assert bars[0].volume == 0


def test_fetch_empty_body_returns_empty(monkeypatch):
    monkeypatch.setattr(ss, "_http_get", lambda url: "")
    assert StooqSource().fetch("MNQ", "1d", 0, 9_999_999_999) == []


def test_fetch_header_only_returns_empty(monkeypatch):
    monkeypatch.setattr(ss, "_http_get", lambda url: "Date,Open,High,Low,Close,Volume\n")
    assert StooqSource().fetch("MNQ", "1d", 0, 9_999_999_999) == []


def test_fetch_propagates_transport_error(monkeypatch):
    def boom(url):
        raise RuntimeError("dns")

    monkeypatch.setattr(ss, "_http_get", boom)
    with pytest.raises(RuntimeError):
        StooqSource().fetch("MNQ", "1d", 0, 9_999_999_999)
