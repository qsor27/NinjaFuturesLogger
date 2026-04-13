import pytest
from pydantic import ValidationError

from models.position import IntegrityIssue, Position


def _pos_kwargs(**overrides):
    base = dict(
        account="Sim101",
        instrument="MNQ",
        entry_execution_id="abc123",
        side="Long",
        entry_time=1_700_000_000,
        exit_time=1_700_000_300,
        quantity=3,
        entry_price=4237.75,
        exit_price=4240.00,
        points_pnl=2.25,
        dollars_pnl=13.50,
        commission=5.00,
        duration_minutes=5.0,
        execution_ids=["abc123", "abc124"],
    )
    base.update(overrides)
    return base


def test_position_accepts_valid_long():
    p = Position(**_pos_kwargs())
    assert p.side == "Long"
    assert p.quantity == 3
    assert p.execution_ids == ["abc123", "abc124"]


def test_position_rejects_invalid_side():
    with pytest.raises(ValidationError):
        Position(**_pos_kwargs(side="Buy"))


def test_position_open_fields_nullable():
    p = Position(
        **_pos_kwargs(
            exit_time=None,
            exit_price=None,
            points_pnl=None,
            dollars_pnl=None,
            duration_minutes=None,
        )
    )
    assert p.exit_time is None
    assert p.points_pnl is None


def test_position_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Position(**_pos_kwargs(bogus=1))


def test_integrity_issue_accepts_valid():
    issue = IntegrityIssue(
        account="Sim101",
        instrument="MNQ",
        execution_id="abc123",
        severity="high",
        type="position_column_mismatch",
        description="builder saw 3 L, CSV said 2 L",
    )
    assert issue.severity == "high"


def test_integrity_issue_rejects_bad_severity():
    with pytest.raises(ValidationError):
        IntegrityIssue(
            account="Sim101",
            instrument="MNQ",
            execution_id="abc123",
            severity="huge",
            type="x",
            description="y",
        )
