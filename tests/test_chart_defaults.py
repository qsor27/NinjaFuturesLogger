from services.chart_defaults import (
    DEFAULT_TIMEFRAME,
    VOLUME_VISIBLE_DEFAULT,
    get_defaults,
)


def test_default_timeframe_is_one_minute():
    assert DEFAULT_TIMEFRAME == "1m"


def test_volume_visible_default_is_true():
    assert VOLUME_VISIBLE_DEFAULT is True


def test_get_defaults_returns_both_keys():
    d = get_defaults()
    assert d == {
        "default_timeframe": "1m",
        "volume_visible_default": True,
    }


def test_get_defaults_returns_a_fresh_dict_each_call():
    a = get_defaults()
    a["default_timeframe"] = "1d"
    b = get_defaults()
    assert b["default_timeframe"] == "1m"
