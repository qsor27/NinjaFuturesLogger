"""Plan 13 seam tests retained as a defensive-fallback smoke on the module
constants. The DB-backed behavior lives in test_chart_defaults_db.py."""

from services.chart_defaults import DEFAULT_TIMEFRAME, VOLUME_VISIBLE_DEFAULT


def test_default_timeframe_constant():
    assert DEFAULT_TIMEFRAME == "5m"


def test_volume_visible_default_is_true():
    assert VOLUME_VISIBLE_DEFAULT is True
