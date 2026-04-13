import time

from services.ohlc.registry import (
    SourceRegistry,
    build_default_registry,
)
from services.ohlc.stooq_source import StooqSource
from services.ohlc.yfinance_source import YfinanceSource


def _clock():
    return int(time.time())


def test_default_registry_yfinance_first():
    reg = build_default_registry(clock=_clock)
    assert [s.name for s, _b in reg.entries] == ["yfinance", "stooq"]


def test_sources_for_filters_by_supported_timeframe():
    reg = build_default_registry(clock=_clock)
    one_min = list(reg.sources_for("1m"))
    one_day = list(reg.sources_for("1d"))
    assert [s.name for s, _b in one_min] == ["yfinance"]
    assert [s.name for s, _b in one_day] == ["yfinance", "stooq"]


def test_sources_for_skips_open_breakers():
    yf = YfinanceSource()
    st = StooqSource()
    reg = SourceRegistry(clock=_clock)
    reg.register(yf, failure_threshold=3, cooldown_seconds=600)
    reg.register(st, failure_threshold=3, cooldown_seconds=1800)

    # Trip yfinance breaker
    yf_breaker = reg.entries[0][1]
    for _ in range(3):
        yf_breaker.record_failure(RuntimeError("boom"))

    available = list(reg.sources_for("1d"))
    assert [s.name for s, _b in available] == ["stooq"]


def test_status_snapshots_returns_one_per_source():
    reg = build_default_registry(clock=_clock)
    snaps = reg.status_snapshots()
    assert {s["name"] for s in snaps} == {"yfinance", "stooq"}
