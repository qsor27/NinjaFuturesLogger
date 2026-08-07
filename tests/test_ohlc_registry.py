import time

from services.ohlc.registry import build_default_registry


def _clock():
    return int(time.time())


def test_default_registry_yfinance_first():
    reg = build_default_registry(clock=_clock)
    assert [s.name for s, _b in reg.entries] == ["yfinance", "stooq"]


def test_status_snapshots_returns_one_per_source():
    reg = build_default_registry(clock=_clock)
    snaps = reg.status_snapshots()
    assert {s["name"] for s in snaps} == {"yfinance", "stooq"}


def test_default_registry_has_plan18_tuning():
    reg = build_default_registry(clock=_clock)
    yf = reg.entries[0][1]
    assert yf.failure_threshold == 3
    assert yf.base_cooldown_seconds == 300
    assert yf.base_cooldown_rate_limit_seconds == 3600
    assert yf.max_cooldown_seconds == 12 * 3600
    assert yf.backoff_multiplier == 4.0
    assert yf.jitter_fraction == 0.15

    st = reg.entries[1][1]
    assert st.failure_threshold == 3
    assert st.base_cooldown_seconds == 600
    assert st.base_cooldown_rate_limit_seconds == 1800
    assert st.max_cooldown_seconds == 21600
    assert st.backoff_multiplier == 2.0
    assert st.jitter_fraction == 0.15


def test_yfinance_breaker_tuned_for_rate_limit_conservatism():
    from services.ohlc.registry import build_default_registry

    reg = build_default_registry(clock=lambda: 0)
    yf_breaker = next(b for s, b in reg.entries if s.name == "yfinance")
    assert yf_breaker.base_cooldown_rate_limit_seconds == 3600
    assert yf_breaker.max_cooldown_seconds == 12 * 3600
    assert yf_breaker.backoff_multiplier == 4.0
