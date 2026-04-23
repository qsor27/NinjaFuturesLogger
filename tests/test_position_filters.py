from models.position import Position
from services.position_filters import PositionFilter, apply_filters, paginate


def _pos(
    entry_id="e",
    account="Sim101",
    instrument="MNQ",
    side="Long",
    entry_time=1000,
    dollars_pnl=5.0,
    commission=0.5,
):
    return Position(
        account=account,
        instrument=instrument,
        entry_execution_id=entry_id,
        side=side,
        entry_time=entry_time,
        exit_time=entry_time + 60,
        quantity=1,
        entry_price=100.0,
        exit_price=101.0,
        points_pnl=1.0,
        dollars_pnl=dollars_pnl,
        commission=commission,
        duration_minutes=1.0,
        execution_ids=[entry_id],
    )


def test_apply_filters_account():
    positions = [_pos(entry_id="a", account="X"), _pos(entry_id="b", account="Y")]
    out = apply_filters(positions, PositionFilter(accounts=("X",)))
    assert [p.entry_execution_id for p in out] == ["a"]


def test_apply_filters_instrument():
    positions = [_pos(entry_id="a", instrument="MNQ"), _pos(entry_id="b", instrument="ES")]
    out = apply_filters(positions, PositionFilter(instrument="ES"))
    assert [p.entry_execution_id for p in out] == ["b"]


def test_apply_filters_side():
    positions = [_pos(entry_id="a", side="Long"), _pos(entry_id="b", side="Short")]
    out = apply_filters(positions, PositionFilter(side="Short"))
    assert [p.entry_execution_id for p in out] == ["b"]


def test_apply_filters_outcome_winner():
    positions = [
        _pos(entry_id="a", dollars_pnl=10.0, commission=1.0),  # winner
        _pos(entry_id="b", dollars_pnl=-10.0, commission=1.0),  # loser
    ]
    out = apply_filters(positions, PositionFilter(outcome="winner"))
    assert [p.entry_execution_id for p in out] == ["a"]


def test_apply_filters_date_range():
    positions = [
        _pos(entry_id="a", entry_time=100),
        _pos(entry_id="b", entry_time=500),
        _pos(entry_id="c", entry_time=1000),
    ]
    out = apply_filters(
        positions,
        PositionFilter(entry_time_min=200, entry_time_max=900),
    )
    assert [p.entry_execution_id for p in out] == ["b"]


def test_apply_filters_compose_and():
    positions = [
        _pos(entry_id="a", account="X", side="Long"),
        _pos(entry_id="b", account="X", side="Short"),
        _pos(entry_id="c", account="Y", side="Long"),
    ]
    out = apply_filters(positions, PositionFilter(accounts=("X",), side="Long"))
    assert [p.entry_execution_id for p in out] == ["a"]


def test_apply_filters_no_filters_returns_all():
    positions = [_pos(entry_id="a"), _pos(entry_id="b")]
    out = apply_filters(positions, PositionFilter())
    assert len(out) == 2


def test_paginate_first_page():
    positions = [_pos(entry_id=str(i)) for i in range(10)]
    page, total = paginate(positions, page=1, page_size=3)
    assert [p.entry_execution_id for p in page] == ["0", "1", "2"]
    assert total == 10


def test_paginate_last_page():
    positions = [_pos(entry_id=str(i)) for i in range(10)]
    page, total = paginate(positions, page=4, page_size=3)
    assert [p.entry_execution_id for p in page] == ["9"]
    assert total == 10


def test_paginate_out_of_range_empty():
    positions = [_pos(entry_id=str(i)) for i in range(10)]
    page, total = paginate(positions, page=10, page_size=3)
    assert page == []
    assert total == 10


def test_paginate_clamps_negative_page_to_one():
    positions = [_pos(entry_id=str(i)) for i in range(3)]
    page, total = paginate(positions, page=0, page_size=50)
    assert len(page) == 3
    assert total == 3


def test_apply_filters_accounts_empty_means_all():
    positions = [_pos(entry_id="a", account="X"), _pos(entry_id="b", account="Y")]
    out = apply_filters(positions, PositionFilter())  # default accounts = ()
    assert [p.entry_execution_id for p in out] == ["a", "b"]


def test_apply_filters_accounts_multi():
    positions = [
        _pos(entry_id="a", account="X"),
        _pos(entry_id="b", account="Y"),
        _pos(entry_id="c", account="Z"),
    ]
    out = apply_filters(positions, PositionFilter(accounts=("X", "Z")))
    assert [p.entry_execution_id for p in out] == ["a", "c"]


def test_apply_filters_accounts_unknown_name_yields_nothing():
    positions = [_pos(entry_id="a", account="X"), _pos(entry_id="b", account="Y")]
    out = apply_filters(positions, PositionFilter(accounts=("does-not-exist",)))
    assert out == []
