from models.execution import Execution
from models.markers import Marker
from services.markers import build_markers


def _exec(
    *,
    nt_execution_id: str,
    timestamp: int,
    side: str,
    quantity: int,
    price: float,
) -> Execution:
    return Execution(
        nt_execution_id=nt_execution_id,
        account="Sim",
        instrument="MNQ",
        timestamp=timestamp,
        side=side,
        original_action=side,
        quantity=quantity,
        price=price,
        commission=0.0,
        entry_exit="Entry" if side == "Buy" else "Exit",
        position_after="1 L" if side == "Buy" else "-",
        source_order_id=None,
        source_filename="f.csv",
        imported_at=timestamp,
    )


def test_empty_executions_yields_empty_markers():
    assert build_markers([]) == []


def test_one_execution_one_marker():
    e = _exec(nt_execution_id="abc", timestamp=100, side="Buy", quantity=2, price=100.5)
    out = build_markers([e])
    assert out == [
        Marker(time=100, price=100.5, side="Buy", quantity=2, label="abc")
    ]


def test_marker_preserves_input_order():
    a = _exec(nt_execution_id="a", timestamp=300, side="Buy", quantity=1, price=10.0)
    b = _exec(nt_execution_id="b", timestamp=100, side="Sell", quantity=1, price=11.0)
    c = _exec(nt_execution_id="c", timestamp=200, side="Buy", quantity=1, price=12.0)
    out = build_markers([a, b, c])
    # build_markers does NOT sort — the route hands sorted executions in.
    # Preserving input order keeps the function pure and predictable.
    assert [m.label for m in out] == ["a", "b", "c"]


def test_marker_side_mirrors_execution_side():
    e1 = _exec(nt_execution_id="x", timestamp=1, side="Buy", quantity=1, price=1.0)
    e2 = _exec(nt_execution_id="y", timestamp=2, side="Sell", quantity=1, price=1.0)
    sides = [m.side for m in build_markers([e1, e2])]
    assert sides == ["Buy", "Sell"]


def test_marker_label_is_real_execution_id_no_suffix():
    # Even though build_positions may emit synthetic 'abc#close' / 'abc#open'
    # execution_ids in Position.execution_ids, the markers service operates on
    # raw Execution rows (one row per real fill in the executions table). The
    # label is therefore always the real id, and the route is responsible for
    # passing only deduped real rows.
    e = _exec(nt_execution_id="real-id", timestamp=42, side="Buy", quantity=3, price=10.0)
    [m] = build_markers([e])
    assert m.label == "real-id"
    assert "#" not in m.label
