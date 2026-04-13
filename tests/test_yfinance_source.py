import pytest

from models.bar import Bar
from services.ohlc import yfinance_source as yfs
from services.ohlc.yfinance_source import YfinanceSource


class _FakeDF:
    """Minimal stand-in for pandas.DataFrame that supports the few accesses
    the adapter makes — itertuples-style iteration and an `empty` property."""

    def __init__(self, records):
        self._records = records

    @property
    def empty(self):
        return not self._records

    def itertuples(self, index=True, name="Bar"):
        yield from self._records


class _Row:
    def __init__(self, ts_unix, o, h, lo, c, v):
        self.Index = _FakeTs(ts_unix)
        self.Open = o
        self.High = h
        self.Low = lo
        self.Close = c
        self.Volume = v


class _FakeTs:
    def __init__(self, unix):
        self._unix = unix

    def timestamp(self):
        return self._unix


def test_supported_timeframes_includes_1m_through_1d():
    s = YfinanceSource()
    for tf in ("1m", "5m", "15m", "1h", "1d"):
        assert tf in s.supported_timeframes


def test_name_is_yfinance():
    assert YfinanceSource().name == "yfinance"


def test_fetch_unknown_instrument_returns_empty(monkeypatch):
    s = YfinanceSource()
    bars = s.fetch("ZZZ_NOT_REAL", "1m", 1_700_000_000, 1_700_001_000)
    assert bars == []


def test_fetch_returns_normalized_bars(monkeypatch):
    rows = [
        _Row(1_700_000_060, 4237.75, 4238.50, 4237.50, 4238.25, 12),
        _Row(1_700_000_120, 4238.25, 4239.00, 4238.00, 4238.75, 8),
    ]

    def fake_download(symbol, *, start, end, interval):
        assert symbol == "MNQ=F"
        assert interval == "1m"
        return _FakeDF(rows)

    monkeypatch.setattr(yfs, "_download", fake_download)
    bars = YfinanceSource().fetch("MNQ", "1m", 1_700_000_000, 1_700_000_180)
    assert len(bars) == 2
    assert all(isinstance(b, Bar) for b in bars)
    assert [b.time for b in bars] == [1_700_000_060, 1_700_000_120]
    assert all(b.source == "yfinance" for b in bars)
    assert all(b.timeframe == "1m" for b in bars)
    assert all(b.instrument == "MNQ" for b in bars)


def test_fetch_returns_empty_for_empty_dataframe(monkeypatch):
    monkeypatch.setattr(yfs, "_download", lambda *a, **k: _FakeDF([]))
    assert YfinanceSource().fetch("MNQ", "1m", 1, 2) == []


def test_fetch_propagates_transport_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network")

    monkeypatch.setattr(yfs, "_download", boom)
    with pytest.raises(RuntimeError):
        YfinanceSource().fetch("MNQ", "1m", 1, 2)


def test_fetch_volume_nan_becomes_zero(monkeypatch):
    nan = float("nan")
    rows = [_Row(1_700_000_060, 1.0, 1.0, 1.0, 1.0, nan)]
    monkeypatch.setattr(yfs, "_download", lambda *a, **k: _FakeDF(rows))
    bars = YfinanceSource().fetch("MNQ", "1m", 1_700_000_000, 1_700_000_120)
    assert bars[0].volume == 0
