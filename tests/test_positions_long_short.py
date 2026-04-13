from models.execution import Execution
from services.positions import build_positions


def _ex(
    eid: str,
    side: str,
    qty: int,
    price: float,
    ts: int,
    *,
    account: str = "Sim101",
    instrument: str = "MNQ",
    entry_exit: str = "Entry",
    position_after: str | None = "1 L",
    commission: float = 0.0,
) -> Execution:
    return Execution(
        nt_execution_id=eid,
        account=account,
        instrument=instrument,
        timestamp=ts,
        side=side,
        original_action=side,
        quantity=qty,
        price=price,
        commission=commission,
        entry_exit=entry_exit,
        position_after=position_after,
        source_order_id=None,
        source_filename="f.csv",
        imported_at=ts,
    )


def test_simple_long_round_trip():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="-"),
    ]
    positions, _issues = build_positions(exs)
    assert len(positions) == 1
    p = positions[0]
    assert p.side == "Long"
    assert p.entry_execution_id == "e1"
    assert p.quantity == 1
    assert p.entry_price == 4000.0
    assert p.exit_price == 4010.0
    assert p.entry_time == 100
    assert p.exit_time == 200
    assert p.execution_ids == ["e1", "e2"]


def test_simple_short_round_trip():
    exs = [
        _ex("e1", "Sell", 1, 4100.0, 100, position_after="1 S"),
        _ex("e2", "Buy", 1, 4090.0, 200, entry_exit="Exit", position_after="-"),
    ]
    positions, _issues = build_positions(exs)
    assert len(positions) == 1
    p = positions[0]
    assert p.side == "Short"
    assert p.entry_execution_id == "e1"
    assert p.quantity == 1
    assert p.entry_price == 4100.0
    assert p.exit_price == 4090.0


def test_two_sequential_long_positions():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="-"),
        _ex("e3", "Buy", 1, 4020.0, 300, position_after="1 L"),
        _ex("e4", "Sell", 1, 4030.0, 400, entry_exit="Exit", position_after="-"),
    ]
    positions, _issues = build_positions(exs)
    assert len(positions) == 2
    assert positions[0].entry_execution_id == "e1"
    assert positions[1].entry_execution_id == "e3"


def test_mixed_long_then_short_positions():
    exs = [
        _ex("e1", "Buy", 2, 4000.0, 100, position_after="2 L"),
        _ex("e2", "Sell", 2, 4010.0, 200, entry_exit="Exit", position_after="-"),
        _ex("e3", "Sell", 1, 4100.0, 300, position_after="1 S"),
        _ex("e4", "Buy", 1, 4095.0, 400, entry_exit="Exit", position_after="-"),
    ]
    positions, _issues = build_positions(exs)
    assert len(positions) == 2
    assert positions[0].side == "Long"
    assert positions[1].side == "Short"


def test_multi_fill_long_position_groups_correctly():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Buy", 2, 4002.0, 200, position_after="3 L"),
        _ex("e3", "Sell", 3, 4010.0, 300, entry_exit="Exit", position_after="-"),
    ]
    positions, _issues = build_positions(exs)
    assert len(positions) == 1
    assert positions[0].execution_ids == ["e1", "e2", "e3"]
    assert positions[0].quantity == 3
