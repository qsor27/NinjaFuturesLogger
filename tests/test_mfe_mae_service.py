from pathlib import Path

from db import connect
from migrations import run_migrations
from models.bar import Bar
from models.position import Position
from services.mfe_mae import compute_mfe_mae, load_and_compute
from services.ohlc.store import insert_many


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
    assert r.mfe_price == 103.0
    assert r.mae_price == 99.0


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
    assert r.mfe_price == 100.5
    assert r.mae_price == 97.0


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
    assert r.mfe_price == 97.0
    assert r.mae_price == 101.0


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
    assert r.mfe_price == 100.0
    assert r.mae_price == 100.0


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


def test_load_and_compute_uses_bars_table(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    try:
        run_migrations(conn, Path("migrations"))
        # Seed bars that straddle the position window.
        insert_many(
            conn,
            [
                _bar(1060, high=103.0, low=99.0, instrument="TEST"),
                _bar(1120, high=102.0, low=100.0, instrument="TEST"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    p = _pos()
    r = load_and_compute(db_path, p)
    assert r is not None
    assert r.mfe_dollars == 3.0
    assert r.mae_dollars == -1.0


def test_load_and_compute_widens_query_for_sub_minute_scalp(tmp_path: Path):
    # Regression: read_range is [start, end). A scalp entirely inside one
    # bar must still fetch the containing bar, whose open-time is BEFORE
    # entry. If load_and_compute queried with start=entry_time, the bar
    # would never reach compute_mfe_mae and coverage would be 0%.
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    try:
        run_migrations(conn, Path("migrations"))
        insert_many(
            conn,
            [_bar(960, high=103.0, low=98.0, instrument="TEST")],
        )
        conn.commit()
    finally:
        conn.close()

    p = _pos(
        side="Long",
        entry_price=100.0,
        exit_price=101.0,
        entry_time=983,
        exit_time=1008,
        qty=1,
        dollars_pnl=1.0,
        points_pnl=1.0,
    )
    r = load_and_compute(db_path, p)
    assert r is not None
    assert r.coverage == 1.0
    assert r.mfe_dollars == 3.0
    assert r.mae_dollars == -2.0


def test_load_and_compute_open_position_returns_none(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    try:
        run_migrations(conn, Path("migrations"))
    finally:
        conn.close()

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
    assert load_and_compute(db_path, p) is None


def test_efficiency_distribution_buckets_winners_and_losers(tmp_config):
    """End-to-end through StatisticsService.efficiency_distribution."""
    from models.statistics import StatsFilter
    from services.statistics import StatisticsService

    # Seed two closed positions: one winner (~67% capture), one loser
    # (~67% risk). Enough 1m bars in each window to clear the 0.8 coverage
    # threshold (default CME session ≈ 17 slots per 1000-second window).
    conn = connect(tmp_config.db_path)
    try:
        run_migrations(conn, Path("migrations"))
        conn.executemany(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp,"
            " side, original_action, quantity, price, commission, entry_exit,"
            " position_after, source_order_id, source_filename, imported_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "W1",
                    "A",
                    "TEST",
                    1000,
                    "Buy",
                    "Buy",
                    1,
                    100.0,
                    0.0,
                    "Entry",
                    1,
                    "O1",
                    "f.csv",
                    0,
                ),
                (
                    "W2",
                    "A",
                    "TEST",
                    2000,
                    "Sell",
                    "Sell",
                    1,
                    102.0,
                    0.0,
                    "Exit",
                    0,
                    "O2",
                    "f.csv",
                    0,
                ),
                (
                    "L1",
                    "A",
                    "TEST",
                    3000,
                    "Buy",
                    "Buy",
                    1,
                    100.0,
                    0.0,
                    "Entry",
                    1,
                    "O3",
                    "f.csv",
                    0,
                ),
                (
                    "L2",
                    "A",
                    "TEST",
                    4000,
                    "Sell",
                    "Sell",
                    1,
                    99.0,
                    0.0,
                    "Exit",
                    0,
                    "O4",
                    "f.csv",
                    0,
                ),
            ],
        )
        # Winner window [1000, 2000]: bars with one high=103 (MFE=+$3),
        # and one low=99 (MAE=-$1). realized=+$2. capture=2/3≈0.667 → bucket 6.
        # Loser window [3000, 4000]: bars with one low=97 (MAE=-$3),
        # and one high=100.5 (MFE=+$0.5). realized=-$1. risk=1-1/3≈0.667 → bucket 6.
        bars = []
        for t in range(1020, 2000, 60):
            high = 103.0 if t == 1080 else 100.5
            low = 99.0 if t == 1140 else 100.0
            bars.append(
                Bar(
                    instrument="TEST",
                    timeframe="1m",
                    time=t,
                    open=100.5,
                    high=high,
                    low=low,
                    close=101.0,
                    volume=0,
                    source="test",
                )
            )
        for t in range(3020, 4000, 60):
            high = 100.5 if t == 3080 else 100.0
            low = 97.0 if t == 3140 else 98.0
            bars.append(
                Bar(
                    instrument="TEST",
                    timeframe="1m",
                    time=t,
                    open=99.5,
                    high=high,
                    low=low,
                    close=98.5,
                    volume=0,
                    source="test",
                )
            )
        insert_many(conn, bars)
        conn.commit()
    finally:
        conn.close()

    svc = StatisticsService(tmp_config)
    result = svc.efficiency_distribution(StatsFilter())
    assert result.n_winners == 1
    assert result.n_losers == 1
    assert result.n_below_coverage == 0
    assert sum(b.count for b in result.capture_buckets) == 1
    assert sum(b.count for b in result.risk_buckets) == 1
    # Capture efficiency of ~0.667 → bucket index 6 (0.6..0.7).
    assert result.capture_buckets[6].count == 1
    assert result.risk_buckets[6].count == 1


def test_sub_minute_scalp_uses_overlapping_bar():
    # 25-second Long trade inside one 1m bar. The containing bar opens at
    # time=960 (before entry) and has high=103, low=98. The old filter
    # `entry <= b.time <= exit` would exclude this bar because its open-time
    # is before entry. The new overlap filter must include it.
    p = _pos(
        side="Long",
        entry_price=100.0,
        exit_price=101.0,
        entry_time=983,
        exit_time=1008,
        qty=1,
        dollars_pnl=1.0,
        points_pnl=1.0,
    )
    bars = [_bar(time=960, high=103.0, low=98.0)]
    result = compute_mfe_mae(p, bars)
    assert result is not None
    assert result.coverage == 1.0
    # Long MFE uses bar.high, MAE uses bar.low
    assert result.mfe_dollars == 3.0  # (103 - 100) * 1 * mult(1.0 for TEST)
    assert result.mae_dollars == -2.0  # (98 - 100) * 1 * mult
    assert result.mfe_time == 960
    assert result.mae_time == 960


def test_zero_duration_trade_uses_containing_bar():
    # Entry and exit at the same unix second. One bar opens at time=960,
    # covering [960, 1020); the instant trade at t=1000 must pick it up.
    p = _pos(
        side="Long",
        entry_price=100.0,
        exit_price=100.0,
        entry_time=1000,
        exit_time=1000,
        qty=2,
        dollars_pnl=0.0,
        points_pnl=0.0,
    )
    bars = [_bar(time=960, high=105.0, low=95.0)]
    result = compute_mfe_mae(p, bars)
    assert result is not None
    assert result.coverage == 1.0
    assert result.mfe_dollars == 10.0  # (105 - 100) * 2
    assert result.mae_dollars == -10.0  # (95 - 100) * 2


def test_mid_minute_entry_includes_partial_first_bar():
    # 2.5-minute Long trade starting 30s into a minute. The first bar
    # (time=0) overlaps the last 30s of the trade's first minute and must
    # appear in `in_window`; that bar carries the session high.
    p = _pos(
        side="Long",
        entry_price=100.0,
        exit_price=101.0,
        entry_time=30,
        exit_time=180,
        qty=1,
        dollars_pnl=1.0,
        points_pnl=1.0,
    )
    bars = [
        _bar(time=0, high=110.0, low=99.0),    # partial-overlap bar with the peak
        _bar(time=60, high=102.0, low=99.5),
        _bar(time=120, high=101.5, low=99.0),
    ]
    result = compute_mfe_mae(p, bars)
    assert result is not None
    # The first bar's high=110 wins MFE only if it's included.
    assert result.mfe_dollars == 10.0  # (110 - 100) * 1
    assert result.mfe_time == 0


def test_exit_on_minute_boundary_excludes_next_bar():
    # Exit at exactly t=120. The bar opening at time=120 starts AT exit, so
    # no trade-active time overlaps it — it must be excluded. Bars at 0 and
    # 60 are both included (0 partially, 60 fully).
    p = _pos(
        side="Long",
        entry_price=100.0,
        exit_price=100.5,
        entry_time=30,
        exit_time=120,
        qty=1,
        dollars_pnl=0.5,
        points_pnl=0.5,
    )
    bars = [
        _bar(time=0, high=101.0, low=99.5),
        _bar(time=60, high=101.5, low=99.0),
        _bar(time=120, high=999.0, low=0.01),  # must NOT influence MFE/MAE
    ]
    result = compute_mfe_mae(p, bars)
    assert result is not None
    # If the t=120 bar leaked in, MFE would become 899.0 and MAE -99.99.
    assert result.mfe_dollars == 1.5  # (101.5 - 100) * 1 from the t=60 bar
    assert result.mae_dollars == -1.0  # (99.0 - 100) * 1 from the t=60 bar
