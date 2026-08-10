import random

from services.review_deck import (
    crop_boundary,
    net_pnl,
    order_deck,
    synthesize_partial_bar,
)
from tests.conftest import make_bar, make_position


def _card(entry_id, entry_time=1000):
    from services.review_deck import card_from_position

    return card_from_position(make_position(entry_execution_id=entry_id, entry_time=entry_time))


# --- crop boundary -----------------------------------------------------------


def test_crop_boundary_mid_minute():
    # entry at 10:30:37 -> boundary is 10:30:00; the 10:30 bar is EXCLUDED
    assert crop_boundary(637) == 600


def test_crop_boundary_exact_minute():
    # entry at exactly :00 still excludes the bar that starts at that second
    assert crop_boundary(600) == 600


# --- net pnl -----------------------------------------------------------------


def test_net_pnl_subtracts_commission():
    p = make_position(dollars_pnl=10.0, commission=1.5)
    assert net_pnl(p) == 8.5


# --- partial bar synthesis ---------------------------------------------------


def test_partial_bar_aggregates_only_pre_boundary_minutes():
    # 5m bucket starting at 600; boundary 780 (entry inside minute 780..840)
    bars = [
        make_bar(time=600, open=10.0, high=12.0, low=9.0, close=11.0, volume=5),
        make_bar(time=660, open=11.0, high=15.0, low=10.5, close=14.0, volume=7),
        make_bar(time=720, open=14.0, high=14.5, low=8.0, close=9.0, volume=3),
        make_bar(time=780, open=9.0, high=99.0, low=1.0, close=50.0, volume=9),  # leak!
    ]
    partial = synthesize_partial_bar(bars, "5m", 780)
    assert partial is not None
    assert partial.time == 600
    assert partial.timeframe == "5m"
    assert partial.open == 10.0
    assert partial.high == 15.0  # 99.0 from the boundary minute must NOT appear
    assert partial.low == 8.0  # 1.0 from the boundary minute must NOT appear
    assert partial.close == 9.0
    assert partial.volume == 15
    assert partial.source == "derived"


def test_partial_bar_none_when_boundary_on_bucket_edge():
    # boundary 600 with 5m bucket 600..900: zero completed 1m bars in-bucket
    bars = [make_bar(time=540)]
    assert synthesize_partial_bar(bars, "5m", 600) is None


def test_partial_bar_none_on_empty_input():
    assert synthesize_partial_bar([], "5m", 780) is None


# --- deck ordering -----------------------------------------------------------


def test_order_deck_unattempted_first_then_least_recent():
    cards = [_card("a"), _card("b"), _card("c"), _card("d")]
    stats = {"b": (2, 500), "d": (1, 100)}  # a, c never attempted
    ordered = order_deck(cards, stats, random.Random(42))
    ids = [c.entry_execution_id for c in ordered]
    assert set(ids[:2]) == {"a", "c"}  # fresh cards lead (shuffled)
    assert ids[2:] == ["d", "b"]  # then least-recently-attempted first


def test_order_deck_is_deterministic_for_seeded_rng():
    cards = [_card(x) for x in "abcdef"]
    one = order_deck(list(cards), {}, random.Random(7))
    two = order_deck(list(cards), {}, random.Random(7))
    assert [c.entry_execution_id for c in one] == [c.entry_execution_id for c in two]
