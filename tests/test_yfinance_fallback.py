"""Front-month continuous fallback in YfinanceSource.

These tests monkeypatch `_download` so no real Yahoo traffic happens.
"""

from datetime import UTC, datetime

import pandas as pd

import services.ohlc.yfinance_source as yfs


def _window_midpoint_seconds():
    # MNQ JUN26 is front-month from 2026-03-20 through 2026-06-20.
    # Pick 2026-05-01 as a timestamp safely inside the window.
    return int(datetime(2026, 5, 1, tzinfo=UTC).timestamp())


def _tiny_df():
    idx = pd.DatetimeIndex([datetime(2026, 5, 1, 13, 30, tzinfo=UTC)], name="Datetime")
    return pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1234],
        },
        index=idx,
    )


def test_fallback_triggers_when_specific_contract_lookup_fails(monkeypatch):
    calls = []

    def fake_download(symbol, *, start, end, interval):
        calls.append(symbol)
        if symbol.endswith(".CME"):
            raise RuntimeError(f"yfinance lookup failed for {symbol!r}: not found")
        # MNQ=F returns data
        return _tiny_df()

    monkeypatch.setattr(yfs, "_download", fake_download)

    t = _window_midpoint_seconds()
    src = yfs.YfinanceSource()
    bars = src.fetch("MNQ JUN26", "1m", t, t + 3600)

    assert [c for c in calls if c.endswith(".CME")], "specific contract was tried"
    assert "MNQ=F" in calls, "continuous fallback was tried"
    assert len(bars) == 1
    assert bars[0].source == "yfinance-continuous"


def test_no_fallback_when_window_outside_front_month(monkeypatch):
    """Before MNQM26 is front month, fallback is declined — and the lookup
    error re-raises so the outer breaker can escalate."""
    import pytest

    calls = []

    def fake_download(symbol, *, start, end, interval):
        calls.append(symbol)
        if symbol.endswith(".CME"):
            raise RuntimeError(f"yfinance lookup failed for {symbol!r}: not found")
        return _tiny_df()

    monkeypatch.setattr(yfs, "_download", fake_download)

    # 2026-01-15 is before MNQH26 expiry (2026-03-20), so MNQ=F tracks MNQH26.
    t = int(datetime(2026, 1, 15, tzinfo=UTC).timestamp())
    src = yfs.YfinanceSource()
    with pytest.raises(RuntimeError):
        src.fetch("MNQ JUN26", "1m", t, t + 3600)

    assert "MNQ=F" not in calls, "fallback must not fire outside front-month window"


def test_no_fallback_for_continuous_instrument(monkeypatch):
    """A call for plain 'MNQ' should not attempt any fallback, and the
    lookup error must propagate so the breaker records a failure."""
    import pytest

    calls = []

    def fake_download(symbol, *, start, end, interval):
        calls.append(symbol)
        if symbol == "MNQ=F":
            raise RuntimeError("yfinance lookup failed: not found")
        return _tiny_df()

    monkeypatch.setattr(yfs, "_download", fake_download)
    t = _window_midpoint_seconds()
    src = yfs.YfinanceSource()
    with pytest.raises(RuntimeError):
        src.fetch("MNQ", "1m", t, t + 3600)

    assert calls == ["MNQ=F"]


def test_specific_contract_success_skips_fallback(monkeypatch):
    calls = []

    def fake_download(symbol, *, start, end, interval):
        calls.append(symbol)
        return _tiny_df()

    monkeypatch.setattr(yfs, "_download", fake_download)
    t = _window_midpoint_seconds()
    src = yfs.YfinanceSource()
    bars = src.fetch("MNQ JUN26", "1m", t, t + 3600)

    assert calls == ["MNQM26.CME"]
    assert "MNQ=F" not in calls
    assert bars[0].source == "yfinance"
