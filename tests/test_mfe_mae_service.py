from models.bar import Bar
from models.position import Position
from services.mfe_mae import compute_mfe_mae


def _pos(
    *,
    side="Long",
    entry_price=100.0,
    exit_price=102.0,
    entry_time=1000,
    exit_time=2000,
    qty=1,
    dollars_pnl=2.0,
    points_pnl=2.0,
    commission=0.0,
    instrument="TEST",
    account="A",
    eid="E1",
):
    return Position(
        account=account,
        instrument=instrument,
        entry_execution_id=eid,
        side=side,
        entry_time=entry_time,
        exit_time=exit_time,
        quantity=qty,
        entry_price=entry_price,
        exit_price=exit_price,
        points_pnl=points_pnl,
        dollars_pnl=dollars_pnl,
        commission=commission,
        duration_minutes=(exit_time - entry_time) / 60.0,
        execution_ids=[eid],
    )


def _bar(time: int, high: float, low: float, instrument: str = "TEST") -> Bar:
    return Bar(
        instrument=instrument,
        timeframe="1m",
        time=time,
        open=(high + low) / 2,
        high=high,
        low=low,
        close=(high + low) / 2,
        volume=0,
        source="test",
    )


def test_open_position_returns_none():
    p = Position(
        account="A",
        instrument="TEST",
        entry_execution_id="E1",
        side="Long",
        entry_time=1000,
        exit_time=None,
        quantity=1,
        entry_price=100.0,
        exit_price=None,
        points_pnl=None,
        dollars_pnl=None,
        commission=0.0,
        duration_minutes=None,
        execution_ids=["E1"],
    )
    assert compute_mfe_mae(p, []) is None


def test_winner_long_full_coverage():
    # Long entry at 100, exit at 102 (realized = +2 points = +$2 at mult=1).
    # Bar highs reach 103 → MFE = +$3; lows drop to 99 → MAE = -$1.
    # capture_efficiency = 2 / 3 ≈ 0.666…
    bars = [
        _bar(1060, high=101.0, low=100.0),
        _bar(1120, high=103.0, low=99.5),
        _bar(1180, high=102.5, low=99.0),
        _bar(1240, high=102.0, low=101.0),
    ]
    p = _pos()
    r = compute_mfe_mae(p, bars)
    assert r is not None
    assert r.mfe_dollars == 3.0
    assert r.mae_dollars == -1.0
    assert r.mfe_time == 1120
    assert r.mae_time == 1180
    assert r.capture_efficiency is not None
    assert abs(r.capture_efficiency - 2.0 / 3.0) < 1e-9
    assert r.risk_efficiency is None


def test_loser_long_full_coverage():
    # Long entry 100, exit 99 (realized = -1 = -$1).
    # Bar low 97 → MAE = -$3; highs barely above 100 → MFE = +$0.5.
    # risk_efficiency = 1 - 1/3 = 0.666…
    bars = [
        _bar(1060, high=100.5, low=100.0),
        _bar(1120, high=100.2, low=97.0),
        _bar(1180, high=99.5, low=98.0),
    ]
    p = _pos(exit_price=99.0, dollars_pnl=-1.0, points_pnl=-1.0)
    r = compute_mfe_mae(p, bars)
    assert r is not None
    assert r.mfe_dollars == 0.5
    assert r.mae_dollars == -3.0
    assert r.capture_efficiency is None
    assert abs(r.risk_efficiency - (1.0 - 1.0 / 3.0)) < 1e-9


def test_short_direction():
    # Short entry 100, exit 98 (realized = +2 points = +$2 at mult=1).
    # Favorable = entry - low; adverse = entry - high.
    # Bar lows drop to 97 → MFE = +$3; highs reach 101 → MAE = -$1.
    bars = [
        _bar(1060, high=100.5, low=99.0),
        _bar(1120, high=101.0, low=97.0),
    ]
    p = _pos(side="Short", exit_price=98.0)
    r = compute_mfe_mae(p, bars)
    assert r is not None
    assert r.mfe_dollars == 3.0
    assert r.mae_dollars == -1.0


def test_scratch_both_efficiencies_none():
    # Realized = 0 → classify_outcome returns "scratch". Both None.
    bars = [_bar(1060, high=101.0, low=99.0)]
    p = _pos(exit_price=100.0, dollars_pnl=0.0, points_pnl=0.0)
    r = compute_mfe_mae(p, bars)
    assert r is not None
    assert r.capture_efficiency is None
    assert r.risk_efficiency is None


def test_realized_exceeds_mfe_clamped():
    # Thin market: realized = +3 but bars only show high of 101 (MFE=+$1).
    # Efficiency would be 3/1=3, must clamp to 1.0.
    bars = [_bar(1060, high=101.0, low=99.5)]
    p = _pos(exit_price=103.0, dollars_pnl=3.0, points_pnl=3.0)
    r = compute_mfe_mae(p, bars)
    assert r is not None
    assert r.capture_efficiency == 1.0


def test_empty_bars_yields_zero_and_coverage_zero():
    p = _pos()
    r = compute_mfe_mae(p, [])
    assert r is not None
    assert r.mfe_dollars == 0.0
    assert r.mae_dollars == 0.0
    assert r.mfe_time == 1000
    assert r.mae_time == 1000
    assert r.coverage == 0.0
    # Classification: winner (realized=+2, commission=0) but mfe_dollars==0
    # → capture_efficiency must be None (undefined), not 1.0.
    assert r.capture_efficiency is None


def test_bars_outside_window_ignored():
    bars = [
        _bar(500, high=200.0, low=0.0),  # pre-entry, must not count
        _bar(1060, high=101.0, low=100.0),
        _bar(1999, high=102.0, low=99.0),
        _bar(2100, high=500.0, low=-500.0),  # post-exit, must not count
    ]
    p = _pos()
    r = compute_mfe_mae(p, bars)
    assert r is not None
    assert r.mfe_dollars == 2.0
    assert r.mae_dollars == -1.0


def test_multiplier_applied(monkeypatch):
    # Monkey-patch get_multiplier at its home module so services.mfe_mae's
    # imported reference sees the override.
    from services import mfe_mae as svc

    monkeypatch.setattr(svc, "get_multiplier", lambda instr: 5.0)
    bars = [_bar(1060, high=102.0, low=99.0)]
    p = _pos(instrument="MNQ")
    r = compute_mfe_mae(p, bars)
    assert r is not None
    # favorable = (102-100)*1*5 = 10; adverse = (99-100)*1*5 = -5
    assert r.mfe_dollars == 10.0
    assert r.mae_dollars == -5.0
