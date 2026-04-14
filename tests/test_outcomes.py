from models.position import Position
from services.outcomes import classify_outcome


def _pos(**overrides):
    base = dict(
        account="A",
        instrument="MNQ",
        entry_execution_id="e",
        side="Long",
        entry_time=0,
        exit_time=1,
        quantity=1,
        entry_price=100.0,
        exit_price=101.0,
        points_pnl=1.0,
        dollars_pnl=2.0,
        commission=0.5,
        duration_minutes=0.01,
        execution_ids=["e"],
    )
    base.update(overrides)
    return Position(**base)


def test_classify_winner_when_pnl_exceeds_commission():
    assert classify_outcome(_pos(dollars_pnl=10.0, commission=2.0)) == "winner"


def test_classify_loser_when_pnl_below_negative_commission():
    assert classify_outcome(_pos(dollars_pnl=-10.0, commission=2.0)) == "loser"


def test_classify_scratch_within_commission_band_positive():
    assert classify_outcome(_pos(dollars_pnl=1.0, commission=2.0)) == "scratch"


def test_classify_scratch_within_commission_band_negative():
    assert classify_outcome(_pos(dollars_pnl=-1.0, commission=2.0)) == "scratch"


def test_classify_scratch_at_exact_boundary():
    assert classify_outcome(_pos(dollars_pnl=2.0, commission=2.0)) == "scratch"
    assert classify_outcome(_pos(dollars_pnl=-2.0, commission=2.0)) == "scratch"


def test_classify_open_position_is_open():
    p = _pos(
        exit_time=None,
        exit_price=None,
        points_pnl=None,
        dollars_pnl=None,
        duration_minutes=None,
    )
    assert classify_outcome(p) == "open"


def test_classify_zero_commission_scratch_only_at_zero_pnl():
    assert classify_outcome(_pos(dollars_pnl=0.0, commission=0.0)) == "scratch"
    assert classify_outcome(_pos(dollars_pnl=0.01, commission=0.0)) == "winner"
    assert classify_outcome(_pos(dollars_pnl=-0.01, commission=0.0)) == "loser"
