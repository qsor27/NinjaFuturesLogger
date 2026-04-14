import pytest
from pydantic import ValidationError

from models.browsing import (
    LinkGroup,
    LinkGroupDetail,
    LinkMember,
    PageMeta,
    PositionListPage,
)
from models.position import Position


def _pos(**overrides):
    base = dict(
        account="Sim101",
        instrument="MNQ",
        entry_execution_id="a",
        side="Long",
        entry_time=1,
        exit_time=2,
        quantity=1,
        entry_price=100.0,
        exit_price=101.0,
        points_pnl=1.0,
        dollars_pnl=2.0,
        commission=0.5,
        duration_minutes=0.01,
        execution_ids=["a", "b"],
    )
    base.update(overrides)
    return Position(**base)


def test_link_member_minimal():
    m = LinkMember(account="Sim101", instrument="MNQ", entry_execution_id="a", ordinal=0)
    assert m.ordinal == 0


def test_link_member_rejects_unknown_field():
    with pytest.raises(ValidationError):
        LinkMember(account="x", instrument="y", entry_execution_id="z", ordinal=0, bogus=1)


def test_link_group_minimal():
    g = LinkGroup(link_group_id=1, label="trade idea", created_at=100)
    assert g.label == "trade idea"


def test_link_group_nullable_label():
    g = LinkGroup(link_group_id=1, label=None, created_at=100)
    assert g.label is None


def test_link_group_detail_members_list():
    g = LinkGroupDetail(
        link_group_id=1,
        label=None,
        created_at=100,
        members=[
            LinkMember(account="A", instrument="MNQ", entry_execution_id="a", ordinal=0),
            LinkMember(account="A", instrument="MNQ", entry_execution_id="b", ordinal=1),
        ],
    )
    assert len(g.members) == 2


def test_page_meta_shape():
    m = PageMeta(page=1, page_size=50, total=123)
    assert m.total_pages == 3
    assert m.has_next is True
    assert m.has_prev is False


def test_page_meta_single_page_math():
    m = PageMeta(page=1, page_size=50, total=10)
    assert m.total_pages == 1
    assert m.has_next is False
    assert m.has_prev is False


def test_page_meta_empty():
    m = PageMeta(page=1, page_size=50, total=0)
    assert m.total_pages == 0
    assert m.has_next is False
    assert m.has_prev is False


def test_position_list_page_roundtrip():
    p = PositionListPage(
        positions=[_pos()],
        page=PageMeta(page=1, page_size=50, total=1),
    )
    assert len(p.positions) == 1
