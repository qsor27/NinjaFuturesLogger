import pytest

from services.instruments import parse_instrument


def test_plain_root():
    assert parse_instrument("MNQ") == ("MNQ", None)


def test_root_with_contract_suffix():
    assert parse_instrument("MNQ JUN26") == ("MNQ", "JUN26")


def test_multi_space_raises():
    with pytest.raises(ValueError):
        parse_instrument("MNQ JUN 26")


def test_empty_string_raises():
    with pytest.raises(ValueError):
        parse_instrument("")


def test_two_digit_year_six_char_suffix():
    assert parse_instrument("ES MAR26") == ("ES", "MAR26")
