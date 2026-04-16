from services.ohlc.reach import PROVIDER_REACH, is_out_of_reach


def test_provider_reach_table_has_all_intraday_timeframes():
    for tf in ("1m", "5m", "15m", "1h", "1d", "1wk", "1mo"):
        assert tf in PROVIDER_REACH


def test_1m_reach_is_30_days():
    assert PROVIDER_REACH["1m"] == 30 * 86400


def test_5m_and_15m_reach_is_60_days():
    assert PROVIDER_REACH["5m"] == 60 * 86400
    assert PROVIDER_REACH["15m"] == 60 * 86400


def test_1h_reach_is_730_days():
    assert PROVIDER_REACH["1h"] == 730 * 86400


def test_1d_reach_is_effectively_unlimited():
    assert PROVIDER_REACH["1d"] >= 30 * 365 * 86400


def test_is_out_of_reach_flags_old_1m_slot():
    now = 1_000_000_000
    old = now - 31 * 86400
    assert is_out_of_reach("1m", slot_ts=old, now=now) is True


def test_is_out_of_reach_passes_recent_1m_slot():
    now = 1_000_000_000
    recent = now - 3 * 86400
    assert is_out_of_reach("1m", slot_ts=recent, now=now) is False


def test_is_out_of_reach_unknown_timeframe_raises():
    import pytest

    with pytest.raises(ValueError):
        is_out_of_reach("2h", slot_ts=0, now=0)
