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
    instrument="MNQ",
    position_after="1 L",
    commission=0.0,
):
    return Execution(
        nt_execution_id=eid,
        account="Sim101",
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


def test_weighted_entry_price_across_multiple_buys():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Buy", 3, 4004.0, 150, position_after="4 L"),
        _ex("e3", "Sell", 4, 4010.0, 200, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    assert p[0].entry_price == pytest.approx(4003.0)
    assert p[0].exit_price == pytest.approx(4010.0)
    assert p[0].quantity == 4


def test_weighted_exit_price_across_multiple_sells():
    exs = [
        _ex("e1", "Buy", 4, 4000.0, 100, position_after="4 L"),
        _ex("e2", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="3 L"),
        _ex("e3", "Sell", 3, 4020.0, 300, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    assert p[0].exit_price == pytest.approx(4017.5)


def test_long_points_and_dollars_pnl_uses_multiplier():
    exs = [
        _ex("e1", "Buy", 2, 4000.0, 100, position_after="2 L"),
        _ex("e2", "Sell", 2, 4010.0, 200, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    assert p[0].points_pnl == pytest.approx(20.0)
    assert p[0].dollars_pnl == pytest.approx(40.0)


def test_short_points_pnl_is_positive_when_price_falls():
    exs = [
        _ex("e1", "Sell", 1, 4100.0, 100, position_after="1 S"),
        _ex("e2", "Buy", 1, 4090.0, 200, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    assert p[0].points_pnl == pytest.approx(10.0)
    assert p[0].dollars_pnl == pytest.approx(20.0)


def test_commission_summed_across_all_fills():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, commission=1.25, position_after="1 L"),
        _ex(
            "e2",
            "Sell",
            1,
            4010.0,
            200,
            entry_exit="Exit",
            commission=1.25,
            position_after="-",
        ),
    ]
    p, _ = build_positions(exs)
    assert p[0].commission == pytest.approx(2.50)


def test_duration_minutes_computed():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 4010.0, 400, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    assert p[0].duration_minutes == pytest.approx(5.0)


def test_instrument_without_multiplier_falls_back_to_one():
    exs = [
        _ex("e1", "Buy", 1, 100.0, 100, instrument="ZZZ", position_after="1 L"),
        _ex(
            "e2",
            "Sell",
            1,
            110.0,
            200,
            entry_exit="Exit",
            instrument="ZZZ",
            position_after="-",
        ),
    ]
    p, _ = build_positions(exs)
    assert p[0].points_pnl == pytest.approx(10.0)
    assert p[0].dollars_pnl == pytest.approx(10.0)
