import pytest

from routes._params import BadParam, int_arg


def test_returns_default_when_key_absent():
    assert int_arg({}, "limit", default=50) == 50


def test_returns_default_when_value_empty():
    assert int_arg({"limit": ""}, "limit", default=50) == 50


def test_none_default_passes_through():
    assert int_arg({}, "start_ts", default=None) is None


def test_parses_integer_string():
    assert int_arg({"limit": "10"}, "limit", default=50) == 10


def test_parses_negative_integer_when_unbounded():
    assert int_arg({"start_ts": "-5"}, "start_ts", default=None) == -5


def test_rejects_non_integer():
    with pytest.raises(BadParam, match="limit must be an integer"):
        int_arg({"limit": "abc"}, "limit", default=50)


def test_rejects_below_lo():
    with pytest.raises(BadParam, match="limit must be >= 1"):
        int_arg({"limit": "-1"}, "limit", default=50, lo=1, hi=500)


def test_rejects_above_hi():
    with pytest.raises(BadParam, match="limit must be <= 500"):
        int_arg({"limit": "9999"}, "limit", default=50, lo=1, hi=500)


def test_accepts_boundary_values():
    assert int_arg({"limit": "1"}, "limit", default=50, lo=1, hi=500) == 1
    assert int_arg({"limit": "500"}, "limit", default=50, lo=1, hi=500) == 500


def test_bad_param_is_a_value_error():
    assert issubclass(BadParam, ValueError)
