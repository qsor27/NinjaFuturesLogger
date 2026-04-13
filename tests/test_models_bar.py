import pytest
from pydantic import ValidationError

from models.bar import AttemptRecord, Bar, FetchResult


def _bar_kwargs(**overrides):
    base = dict(
        instrument="MNQ",
        timeframe="1m",
        time=1_700_000_000,
        open=4237.75,
        high=4238.50,
        low=4237.50,
        close=4238.25,
        volume=42,
        source="yfinance",
    )
    base.update(overrides)
    return base


def test_bar_accepts_valid():
    b = Bar(**_bar_kwargs())
    assert b.instrument == "MNQ"
    assert b.timeframe == "1m"
    assert b.volume == 42


def test_bar_rejects_invalid_timeframe():
    with pytest.raises(ValidationError):
        Bar(**_bar_kwargs(timeframe="2m"))


def test_bar_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Bar(**_bar_kwargs(adj_close=4238.0))


def test_bar_volume_must_be_int_not_none():
    with pytest.raises(ValidationError):
        Bar(**_bar_kwargs(volume=None))


def test_attempt_record_minimal():
    a = AttemptRecord(source="yfinance", outcome="ok", count=12, error=None)
    assert a.outcome == "ok"
    assert a.count == 12


def test_attempt_record_rejects_invalid_outcome():
    with pytest.raises(ValidationError):
        AttemptRecord(source="yfinance", outcome="maybe", count=0, error=None)


def test_fetch_result_cached():
    r = FetchResult(status="cached", bars_added=0, attempts=[])
    assert r.bars_added == 0
    assert r.attempts == []


def test_fetch_result_with_attempts():
    r = FetchResult(
        status="ok",
        bars_added=12,
        attempts=[
            AttemptRecord(source="yfinance", outcome="ok", count=12, error=None),
        ],
    )
    assert r.bars_added == 12
    assert len(r.attempts) == 1
