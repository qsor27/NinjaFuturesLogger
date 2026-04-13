import pytest
from pydantic import ValidationError

from models.execution import Execution, RejectRecord, TickResult


def _valid_execution_kwargs():
    return dict(
        nt_execution_id="abc123",
        account="Sim101",
        instrument="MNQ",
        timestamp=1_700_000_000,
        side="Buy",
        original_action="Buy",
        quantity=3,
        price=4237.75,
        commission=0.50,
        entry_exit="Entry",
        position_after="3 L",
        source_order_id="ord1",
        source_filename="NinjaTrader_Executions_20260413.csv",
        imported_at=1_700_000_001,
    )


def test_execution_accepts_valid_values():
    e = Execution(**_valid_execution_kwargs())
    assert e.side == "Buy"
    assert e.quantity == 3


def test_execution_rejects_unknown_field():
    kwargs = _valid_execution_kwargs()
    kwargs["bogus"] = 1
    with pytest.raises(ValidationError):
        Execution(**kwargs)


def test_execution_rejects_invalid_side():
    kwargs = _valid_execution_kwargs()
    kwargs["side"] = "BuyToCover"
    with pytest.raises(ValidationError):
        Execution(**kwargs)


def test_execution_rejects_zero_quantity():
    kwargs = _valid_execution_kwargs()
    kwargs["quantity"] = 0
    with pytest.raises(ValidationError):
        Execution(**kwargs)


def test_execution_allows_null_position_after():
    kwargs = _valid_execution_kwargs()
    kwargs["position_after"] = None
    e = Execution(**kwargs)
    assert e.position_after is None


def test_tick_result_basic():
    r = TickResult(
        filename="f.csv",
        status="ok",
        lines_read=10,
        rows_parsed=10,
        rows_inserted=8,
        rows_skipped_duplicate=2,
        rows_rejected=0,
        cursor_before=0,
        cursor_after=1234,
        tick_id=1,
        error=None,
    )
    assert r.status == "ok"


def test_tick_result_rejects_bad_status():
    with pytest.raises(ValidationError):
        TickResult(
            filename="f.csv",
            status="bogus",
            lines_read=0,
            rows_parsed=0,
            rows_inserted=0,
            rows_skipped_duplicate=0,
            rows_rejected=0,
            cursor_before=0,
            cursor_after=0,
            tick_id=None,
            error=None,
        )


def test_reject_record_shape():
    r = RejectRecord(line_number=7, raw_line="oops", reason="bad column count")
    assert r.line_number == 7
