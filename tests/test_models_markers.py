import pytest
from pydantic import ValidationError

from models.markers import Marker


def test_marker_basic_construction():
    m = Marker(
        time=1700000000,
        price=18250.5,
        side="Buy",
        quantity=2,
        label="abc-123",
    )
    assert m.time == 1700000000
    assert m.price == 18250.5
    assert m.side == "Buy"
    assert m.quantity == 2
    assert m.label == "abc-123"


def test_marker_side_must_be_buy_or_sell():
    with pytest.raises(ValidationError):
        Marker(time=1, price=1.0, side="Hold", quantity=1, label="x")


def test_marker_quantity_must_be_int():
    with pytest.raises(ValidationError):
        Marker(time=1, price=1.0, side="Buy", quantity=1.5, label="x")


def test_marker_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        Marker(time=1, price=1.0, side="Buy", quantity=1, label="x", extra="nope")


def test_marker_is_exported_from_models():
    from models import Marker as ReExported

    assert ReExported is Marker
