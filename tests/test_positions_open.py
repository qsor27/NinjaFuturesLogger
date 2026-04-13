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


def test_open_long_position_has_null_exit_fields():
    exs = [_ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L")]
    positions, _ = build_positions(exs)
    assert len(positions) == 1
    p = positions[0]
    assert p.side == "Long"
    assert p.entry_execution_id == "e1"
    assert p.entry_price == 4000.0
    assert p.quantity == 1
    assert p.exit_time is None
    assert p.exit_price is None
    assert p.points_pnl is None
    assert p.dollars_pnl is None
    assert p.duration_minutes is None


def test_open_position_after_closed_ones():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="-"),
        _ex("e3", "Buy", 2, 4020.0, 300, position_after="2 L"),
    ]
    positions, _ = build_positions(exs)
    assert len(positions) == 2
    assert positions[0].exit_time == 200
    assert positions[1].exit_time is None
    assert positions[1].quantity == 2


def test_open_short_position():
    exs = [_ex("e1", "Sell", 1, 4100.0, 100, position_after="1 S")]
    p, _ = build_positions(exs)
    assert len(p) == 1
    assert p[0].side == "Short"
    assert p[0].exit_price is None
