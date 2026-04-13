from models.execution import Execution
from services.positions import build_positions


def _ex(eid, side, qty, price, ts, *, entry_exit="Entry", position_after="1 L"):
    return Execution(
        nt_execution_id=eid,
        account="Sim101",
        instrument="MNQ",
        timestamp=ts,
        side=side,
        original_action=side,
        quantity=qty,
        price=price,
        commission=0.0,
        entry_exit=entry_exit,
        position_after=position_after,
        source_order_id=None,
        source_filename="f.csv",
        imported_at=ts,
    )


def test_unsorted_input_produces_same_result_as_sorted():
    sorted_exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="-"),
    ]
    unsorted_exs = list(reversed(sorted_exs))
    sorted_p, _ = build_positions(sorted_exs)
    unsorted_p, _ = build_positions(unsorted_exs)
    assert len(sorted_p) == len(unsorted_p) == 1
    assert sorted_p[0].entry_execution_id == unsorted_p[0].entry_execution_id
    assert sorted_p[0].exit_price == unsorted_p[0].exit_price


def test_ties_broken_by_execution_id():
    exs = [
        _ex("b", "Sell", 1, 4010.0, 100, entry_exit="Exit", position_after="-"),
        _ex("a", "Buy", 1, 4000.0, 100, position_after="1 L"),
    ]
    p, _ = build_positions(exs)
    assert len(p) == 1
    assert p[0].entry_execution_id == "a"
    assert p[0].execution_ids == ["a", "b"]


def test_different_accounts_and_instruments_are_not_caller_grouped():
    exs = [
        _ex("x", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("y", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    assert len(p) == 1
