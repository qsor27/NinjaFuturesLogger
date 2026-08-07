from services.positions import build_positions
from tests.conftest import make_execution


def _ex(eid, side, qty, price, ts, *, entry_exit="Entry", position_after="1 L"):
    return make_execution(
        eid,
        timestamp=ts,
        side=side,
        original_action=side,
        quantity=qty,
        price=price,
        entry_exit=entry_exit,
        position_after=position_after,
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


def test_build_positions_does_not_group_by_account_or_instrument():
    """build_positions walks whatever sequence it is given: splitting by
    (account, instrument) is the caller's job (services/positions_service.py
    groups before calling). Handing it two accounts collapses them into one walk.
    """
    exs = [
        make_execution(
            "x",
            account="A",
            instrument="MNQ",
            side="Buy",
            original_action="Buy",
            price=4000.0,
            timestamp=100,
            imported_at=100,
            position_after="1 L",
        ),
        make_execution(
            "y",
            account="B",
            instrument="ES",
            side="Sell",
            original_action="Sell",
            price=4010.0,
            timestamp=200,
            imported_at=200,
            entry_exit="Exit",
            position_after="1 S",
        ),
    ]
    p, _ = build_positions(exs)
    assert len(p) == 1


def test_caller_grouping_yields_one_position_per_account_and_instrument():
    exs = [
        make_execution(
            "x",
            account="A",
            instrument="MNQ",
            side="Buy",
            original_action="Buy",
            price=4000.0,
            timestamp=100,
            imported_at=100,
            position_after="1 L",
        ),
        make_execution(
            "y",
            account="B",
            instrument="ES",
            side="Sell",
            original_action="Sell",
            price=4010.0,
            timestamp=200,
            imported_at=200,
            position_after="1 S",
        ),
    ]
    groups: dict[tuple[str, str], list] = {}
    for e in exs:
        groups.setdefault((e.account, e.instrument), []).append(e)

    positions = [p for group in groups.values() for p in build_positions(group)[0]]
    assert len(positions) == 2
    assert {(p.account, p.instrument) for p in positions} == {("A", "MNQ"), ("B", "ES")}
    assert {p.side for p in positions} == {"Long", "Short"}
