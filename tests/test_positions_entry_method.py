import pytest

from models.position import ENTRY_METHODS
from services.entry_method import classify_entry_method, is_counter_trend
from services.positions import build_positions
from tests.conftest import make_execution


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("GateMktNextOpen", "market_next_open"),
        ("GateLmtNextOpen", "limit_next_open"),
        ("GateMktNextOpenCT", "market_next_open"),
        ("GateLmtNextOpenCT", "limit_next_open"),
        ("GateMktNextOpenXY", "manual"),
        ("Entry", "manual"),
        ("Buy", "manual"),
        (None, "unknown"),
        ("", "unknown"),
    ],
)
def test_classify_entry_method(name, expected):
    assert classify_entry_method(name) == expected


def test_entry_methods_tuple_order():
    assert ENTRY_METHODS == ("market_next_open", "limit_next_open", "manual", "unknown")


def _round_trip(entry_name, exit_name="Target1"):
    return [
        make_execution("a", timestamp=1, order_name=entry_name),
        make_execution(
            "b",
            timestamp=2,
            side="Sell",
            original_action="Sell",
            entry_exit="Exit",
            position_after="-",
            order_name=exit_name,
        ),
    ]


@pytest.mark.parametrize(
    ("entry_name", "expected"),
    [
        ("GateMktNextOpen", "market_next_open"),
        ("GateLmtNextOpen", "limit_next_open"),
        ("Entry", "manual"),
        (None, "unknown"),
    ],
)
def test_position_entry_method_comes_from_entry_fill(entry_name, expected):
    positions, _ = build_positions(_round_trip(entry_name))
    assert len(positions) == 1
    assert positions[0].entry_method == expected


def test_exit_order_name_never_decides_entry_method():
    positions, _ = build_positions(_round_trip("Entry", exit_name="GateMktNextOpen"))
    assert positions[0].entry_method == "manual"


def test_open_position_has_entry_method():
    positions, _ = build_positions([make_execution("a", order_name="GateLmtNextOpen")])
    assert positions[0].exit_time is None
    assert positions[0].entry_method == "limit_next_open"


def test_reversal_open_side_inherits_order_name():
    execs = [
        make_execution("a", timestamp=1, quantity=1, order_name="Entry"),
        make_execution(
            "r",
            timestamp=2,
            side="Sell",
            original_action="Sell",
            quantity=2,
            entry_exit="Exit",
            position_after="1 S",
            order_name="GateMktNextOpen",
        ),
    ]
    positions, _ = build_positions(execs)
    assert [p.entry_method for p in positions] == ["manual", "market_next_open"]
    assert positions[1].entry_execution_id == "r#open"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("GateMktNextOpenCT", True),
        ("GateLmtNextOpenCT", True),
        ("GateMktNextOpen", False),
        ("Entry", False),
        (None, False),
    ],
)
def test_is_counter_trend(name, expected):
    assert is_counter_trend(name) is expected
