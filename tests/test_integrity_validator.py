from models.execution import Execution
from services.integrity import cross_check_against_source_position_column


def _ex(eid, side, qty, ts, *, position_after, entry_exit="Entry"):
    return Execution(
        nt_execution_id=eid,
        account="Sim101",
        instrument="MNQ",
        timestamp=ts,
        side=side,
        original_action=side,
        quantity=qty,
        price=4000.0,
        commission=0.0,
        entry_exit=entry_exit,
        position_after=position_after,
        source_order_id=None,
        source_filename="f.csv",
        imported_at=ts,
    )


def test_consistent_position_column_produces_no_issues():
    exs = [
        _ex("e1", "Buy", 1, 100, position_after="1 L"),
        _ex("e2", "Buy", 2, 200, position_after="3 L"),
        _ex("e3", "Sell", 3, 300, position_after="-", entry_exit="Exit"),
    ]
    issues = cross_check_against_source_position_column(exs)
    assert issues == []


def test_mismatched_position_column_produces_high_issue():
    exs = [
        _ex("e1", "Buy", 1, 100, position_after="2 L"),
    ]
    issues = cross_check_against_source_position_column(exs)
    assert len(issues) == 1
    assert issues[0].severity == "high"
    assert issues[0].type == "position_column_mismatch"
    assert issues[0].execution_id == "e1"


def test_mismatched_side_flag_produces_issue():
    exs = [
        _ex("e1", "Buy", 1, 100, position_after="1 S"),
    ]
    issues = cross_check_against_source_position_column(exs)
    assert len(issues) == 1
    assert issues[0].type == "position_column_mismatch"


def test_null_position_column_is_skipped():
    exs = [
        _ex("e1", "Buy", 1, 100, position_after=None),
    ]
    issues = cross_check_against_source_position_column(exs)
    assert issues == []


def test_dash_matches_flat_running_quantity():
    exs = [
        _ex("e1", "Buy", 1, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 200, entry_exit="Exit", position_after="-"),
    ]
    issues = cross_check_against_source_position_column(exs)
    assert issues == []


def test_unparseable_position_column_is_reported():
    exs = [
        _ex("e1", "Buy", 1, 100, position_after="garbage"),
    ]
    issues = cross_check_against_source_position_column(exs)
    assert len(issues) == 1
    assert "garbage" in issues[0].description
