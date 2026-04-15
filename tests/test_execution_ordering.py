from models.execution import Execution
from services.execution_ordering import (
    order_executions_for_walk,
    parse_position_column,
)


def _ex(eid, side, qty, ts, *, position_after, entry_exit="Entry"):
    return Execution(
        nt_execution_id=eid,
        account="Sim101",
        instrument="MNQ",
        timestamp=ts,
        side=side,
        original_action=side,
        quantity=qty,
        price=4000.0,
        commission=0.0,
        entry_exit=entry_exit,
        position_after=position_after,
        source_order_id=None,
        source_filename="f.csv",
        imported_at=ts,
    )


def test_parse_position_column():
    assert parse_position_column("-") == 0
    assert parse_position_column("5 L") == 5
    assert parse_position_column("3 S") == -3
    assert parse_position_column(None) is None
    assert parse_position_column("garbage") is None
    assert parse_position_column("5 X") is None
    assert parse_position_column("-1 L") is None


def test_single_timestamp_preserved_when_no_ties():
    exs = [
        _ex("a", "Buy", 1, 100, position_after="1 L"),
        _ex("b", "Buy", 2, 200, position_after="3 L"),
        _ex("c", "Sell", 3, 300, position_after="-", entry_exit="Exit"),
    ]
    out = order_executions_for_walk(exs)
    assert [e.nt_execution_id for e in out] == ["a", "b", "c"]


def test_ascending_id_tied_group_slice_fills():
    # Single sliced order: _1, _2, _3 — ascending order is correct.
    exs = [
        _ex("577807_1", "Buy", 1, 500, position_after="1 L"),
        _ex("577807_2", "Buy", 2, 500, position_after="3 L"),
        _ex("577807_3", "Buy", 2, 500, position_after="5 L"),
        _ex("577807_4", "Buy", 1, 500, position_after="6 L"),
    ]
    out = order_executions_for_walk(exs)
    assert [e.nt_execution_id for e in out] == [
        "577807_1",
        "577807_2",
        "577807_3",
        "577807_4",
    ]


def test_descending_id_tied_close_all_group():
    # Close-all scenario from real data: 6 L flattened by 4 separate orders
    # all at the same second, IDs ascending but fill order descending.
    entry = _ex("576834_1", "Buy", 6, 1000, position_after="6 L")
    exits_ascending_id = [
        _ex("576842_1", "Sell", 2, 2000, position_after="-", entry_exit="Exit"),
        _ex("576847_1", "Sell", 2, 2000, position_after="2 L", entry_exit="Exit"),
        _ex("576854_1", "Sell", 1, 2000, position_after="4 L", entry_exit="Exit"),
        _ex("576859_1", "Sell", 1, 2000, position_after="5 L", entry_exit="Exit"),
    ]
    out = order_executions_for_walk([entry, *exits_ascending_id])
    assert [e.nt_execution_id for e in out] == [
        "576834_1",
        "576859_1",
        "576854_1",
        "576847_1",
        "576842_1",
    ]


def test_short_cover_tied_group_ascending():
    # Three buys covering a 4-short, ascending id IS correct here.
    short_entry = _ex("578000_1", "Sell", 4, 1000, position_after="4 S")
    covers = [
        _ex("578027_1", "Buy", 2, 2000, position_after="2 S", entry_exit="Exit"),
        _ex("578034_1", "Buy", 1, 2000, position_after="1 S", entry_exit="Exit"),
        _ex("578038_1", "Buy", 1, 2000, position_after="-", entry_exit="Exit"),
    ]
    out = order_executions_for_walk([short_entry, *covers])
    assert [e.nt_execution_id for e in out] == [
        "578000_1",
        "578027_1",
        "578034_1",
        "578038_1",
    ]


def test_fallback_to_id_asc_when_position_after_missing():
    # Tied group, no position_after — helper should fall back to id asc.
    exs = [
        _ex("e2", "Buy", 1, 500, position_after=None),
        _ex("e1", "Buy", 1, 500, position_after=None),
    ]
    out = order_executions_for_walk(exs)
    assert [e.nt_execution_id for e in out] == ["e1", "e2"]


def test_fallback_when_position_after_inconsistent():
    # Garbage pos_after -> fallback id asc, running qty still advances.
    exs = [
        _ex("e2", "Buy", 1, 500, position_after="99 L"),
        _ex("e1", "Buy", 1, 500, position_after="99 L"),
    ]
    out = order_executions_for_walk(exs)
    assert [e.nt_execution_id for e in out] == ["e1", "e2"]
