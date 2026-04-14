import pytest

from models.position import Position
from services.statistics_aggregations import compute_summary


def _pos(
    *,
    eid: str = "e",
    side: str = "Long",
    entry_time: int = 100,
    exit_time: int | None = 200,
    dollars_pnl: float | None = 10.0,
    commission: float = 0.0,
    quantity: int = 1,
    duration_minutes: float | None = 1.0,
) -> Position:
    return Position(
        account="Sim",
        instrument="MNQ",
        entry_execution_id=eid,
        side=side,  # type: ignore[arg-type]
        entry_time=entry_time,
        exit_time=exit_time,
        quantity=quantity,
        entry_price=100.0,
        exit_price=101.0,
        points_pnl=1.0,
        dollars_pnl=dollars_pnl,
        commission=commission,
        duration_minutes=duration_minutes,
        execution_ids=[eid],
    )


def test_compute_summary_empty_input():
    s = compute_summary([])
    assert s.total_positions == 0
    assert s.total_pnl == 0.0
    assert s.wins == 0
    assert s.losses == 0
    assert s.scratches == 0
    assert s.win_rate is None
    assert s.avg_win is None
    assert s.avg_loss is None
    assert s.profit_factor is None
    assert s.largest_win is None
    assert s.largest_loss is None
    assert s.longest_win_streak == 0
    assert s.longest_loss_streak == 0
    assert s.avg_hold_minutes is None
    assert s.median_hold_minutes is None
    assert s.avg_position_size is None
    assert s.open_positions == 0
    assert s.skipped_no_multiplier == 0


def test_compute_summary_single_winner():
    s = compute_summary([_pos(dollars_pnl=50.0, commission=2.0)])
    assert s.total_positions == 1
    assert s.wins == 1
    assert s.losses == 0
    assert s.scratches == 0
    assert s.win_rate == 1.0
    assert s.avg_win == 50.0
    assert s.avg_loss is None
    assert s.profit_factor is None  # no losers
    assert s.largest_win == 50.0
    assert s.largest_loss is None
    assert s.longest_win_streak == 1
    assert s.longest_loss_streak == 0


def test_compute_summary_scratch_band_uses_commission():
    # |dollars_pnl| <= commission means scratch.
    s = compute_summary([_pos(dollars_pnl=2.0, commission=2.0)])
    assert s.scratches == 1
    assert s.wins == 0
    assert s.losses == 0
    assert s.win_rate is None  # 0/(0+0) = null


def test_compute_summary_mixed():
    positions = [
        _pos(eid="a", dollars_pnl=100.0, commission=2.0),  # winner
        _pos(eid="b", dollars_pnl=-50.0, commission=2.0),  # loser
        _pos(eid="c", dollars_pnl=200.0, commission=2.0),  # winner
        _pos(eid="d", dollars_pnl=-100.0, commission=2.0),  # loser
        _pos(eid="e", dollars_pnl=1.0, commission=2.0),  # scratch
    ]
    s = compute_summary(positions)
    assert s.total_positions == 5
    assert s.total_pnl == 151.0
    assert s.wins == 2
    assert s.losses == 2
    assert s.scratches == 1
    assert s.win_rate == 0.5
    assert s.avg_win == 150.0
    assert s.avg_loss == -75.0
    assert s.profit_factor == pytest.approx(2.0)  # 300 / 150
    assert s.largest_win == 200.0
    assert s.largest_loss == -100.0


def test_compute_summary_streaks_alternating():
    # W L W L W -> longest win streak 1, longest loss streak 1
    positions = [
        _pos(eid="1", dollars_pnl=10.0, commission=0.0, exit_time=10),
        _pos(eid="2", dollars_pnl=-10.0, commission=0.0, exit_time=20),
        _pos(eid="3", dollars_pnl=10.0, commission=0.0, exit_time=30),
        _pos(eid="4", dollars_pnl=-10.0, commission=0.0, exit_time=40),
        _pos(eid="5", dollars_pnl=10.0, commission=0.0, exit_time=50),
    ]
    s = compute_summary(positions)
    assert s.longest_win_streak == 1
    assert s.longest_loss_streak == 1


def test_compute_summary_streaks_runs():
    # W W W L L W L L L W -> longest win 3, longest loss 3
    pnls = [10, 10, 10, -10, -10, 10, -10, -10, -10, 10]
    positions = [
        _pos(eid=str(i), dollars_pnl=float(p), commission=0.0, exit_time=10 * (i + 1))
        for i, p in enumerate(pnls)
    ]
    s = compute_summary(positions)
    assert s.longest_win_streak == 3
    assert s.longest_loss_streak == 3


def test_compute_summary_streaks_skip_scratches():
    # Scratches break neither streak.
    positions = [
        _pos(eid="1", dollars_pnl=10.0, commission=0.0, exit_time=10),
        _pos(eid="2", dollars_pnl=10.0, commission=0.0, exit_time=20),
        _pos(eid="3", dollars_pnl=0.0, commission=0.0, exit_time=30),  # scratch
        _pos(eid="4", dollars_pnl=10.0, commission=0.0, exit_time=40),
    ]
    s = compute_summary(positions)
    assert s.longest_win_streak == 3


def test_compute_summary_streaks_ordered_by_exit_time():
    # Out-of-order input; helper sorts by exit_time before walking.
    positions = [
        _pos(eid="3", dollars_pnl=-10.0, commission=0.0, exit_time=30),
        _pos(eid="1", dollars_pnl=10.0, commission=0.0, exit_time=10),
        _pos(eid="2", dollars_pnl=10.0, commission=0.0, exit_time=20),
    ]
    s = compute_summary(positions)
    assert s.longest_win_streak == 2
    assert s.longest_loss_streak == 1


def test_compute_summary_hold_time_median_odd_and_even():
    odd = [
        _pos(eid="1", duration_minutes=1.0),
        _pos(eid="2", duration_minutes=3.0),
        _pos(eid="3", duration_minutes=5.0),
    ]
    even = odd + [_pos(eid="4", duration_minutes=7.0)]
    assert compute_summary(odd).median_hold_minutes == 3.0
    assert compute_summary(even).median_hold_minutes == 4.0


def test_compute_summary_avg_position_size():
    positions = [
        _pos(eid="1", quantity=2),
        _pos(eid="2", quantity=4),
    ]
    assert compute_summary(positions).avg_position_size == 3.0
