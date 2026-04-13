import pytest

from models.execution import Execution
from services.positions import build_positions


def _ex(
    eid,
    side,
    qty,
    price,
    ts,
    *,
    entry_exit="Entry",
    position_after="1 L",
    commission=0.0,
):
    return Execution(
        nt_execution_id=eid,
        account="Sim101",
        instrument="MNQ",
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


def test_long_to_short_reversal_creates_two_positions():
    exs = [
        _ex("e1", "Buy", 3, 4000.0, 100, position_after="3 L"),
        _ex(
            "e2",
            "Sell",
            5,
            4010.0,
            200,
            entry_exit="Exit",
            position_after="2 S",
            commission=2.5,
        ),
    ]
    positions, _ = build_positions(exs)
    assert len(positions) == 2
    p0 = positions[0]
    assert p0.side == "Long"
    assert p0.entry_execution_id == "e1"
    assert p0.quantity == 3
    assert p0.exit_price == pytest.approx(4010.0)
    assert "e2#close" in p0.execution_ids
    p1 = positions[1]
    assert p1.side == "Short"
    assert p1.entry_execution_id == "e2#open"
    assert p1.quantity == 2
    assert p1.exit_time is None
    assert "e2#open" in p1.execution_ids


def test_short_to_long_reversal_creates_two_positions():
    exs = [
        _ex("e1", "Sell", 2, 4100.0, 100, position_after="2 S"),
        _ex("e2", "Buy", 5, 4090.0, 200, entry_exit="Exit", position_after="3 L"),
    ]
    positions, _ = build_positions(exs)
    assert len(positions) == 2
    assert positions[0].side == "Short"
    assert positions[0].quantity == 2
    assert positions[0].exit_price == pytest.approx(4090.0)
    assert positions[1].side == "Long"
    assert positions[1].quantity == 3
    assert positions[1].entry_execution_id == "e2#open"


def test_reversal_commission_split_proportionally():
    exs = [
        _ex("e1", "Buy", 3, 4000.0, 100, commission=0.0, position_after="3 L"),
        _ex(
            "e2",
            "Sell",
            5,
            4010.0,
            200,
            entry_exit="Exit",
            commission=5.0,
            position_after="2 S",
        ),
    ]
    positions, _ = build_positions(exs)
    assert positions[0].commission == pytest.approx(3.0)
    assert positions[1].commission == pytest.approx(2.0)


def test_reversal_followed_by_close():
    exs = [
        _ex("e1", "Buy", 3, 4000.0, 100, position_after="3 L"),
        _ex("e2", "Sell", 5, 4010.0, 200, entry_exit="Exit", position_after="2 S"),
        _ex("e3", "Buy", 2, 4005.0, 300, entry_exit="Exit", position_after="-"),
    ]
    positions, _ = build_positions(exs)
    assert len(positions) == 2
    assert positions[1].exit_time == 300
    assert positions[1].exit_price == pytest.approx(4005.0)
