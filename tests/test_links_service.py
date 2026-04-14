import pytest

from db import connect
from models.browsing import LinkMember
from services.links import (
    add_members,
    create_group,
    delete_group,
    get_group,
    list_groups,
    remove_member,
    rename_group,
)


def _members(*triples):
    return [
        LinkMember(account=a, instrument=i, entry_execution_id=e, ordinal=n)
        for n, (a, i, e) in enumerate(triples)
    ]


def test_create_group_returns_id_and_stores_members(migrated_db):
    group_id = create_group(
        migrated_db,
        label="trade",
        members=_members(("A", "MNQ", "e1"), ("B", "MNQ", "e2")),
        now=100,
    )
    assert isinstance(group_id, int)
    detail = get_group(migrated_db, group_id)
    assert detail.label == "trade"
    assert detail.created_at == 100
    assert [(m.account, m.instrument, m.entry_execution_id) for m in detail.members] == [
        ("A", "MNQ", "e1"),
        ("B", "MNQ", "e2"),
    ]


def test_create_group_preserves_ordinal(migrated_db):
    group_id = create_group(
        migrated_db,
        label=None,
        members=_members(("A", "MNQ", "x"), ("A", "MNQ", "y"), ("A", "MNQ", "z")),
        now=1,
    )
    detail = get_group(migrated_db, group_id)
    assert [m.ordinal for m in detail.members] == [0, 1, 2]


def test_create_group_rejects_empty_members(migrated_db):
    with pytest.raises(ValueError):
        create_group(migrated_db, label=None, members=[], now=1)


def test_create_group_rejects_duplicate_member(migrated_db):
    with pytest.raises(ValueError):
        create_group(
            migrated_db,
            label=None,
            members=_members(("A", "MNQ", "e1"), ("A", "MNQ", "e1")),
            now=1,
        )


def test_get_group_missing_returns_none(migrated_db):
    assert get_group(migrated_db, 9999) is None


def test_list_groups_returns_all(migrated_db):
    id1 = create_group(migrated_db, label="one", members=_members(("A", "M", "a")), now=1)
    id2 = create_group(migrated_db, label="two", members=_members(("A", "M", "b")), now=2)
    groups = list_groups(migrated_db)
    assert {g.link_group_id for g in groups} == {id1, id2}


def test_rename_group(migrated_db):
    gid = create_group(migrated_db, label="old", members=_members(("A", "M", "a")), now=1)
    rename_group(migrated_db, link_group_id=gid, label="new")
    assert get_group(migrated_db, gid).label == "new"


def test_add_members_extends_ordinals(migrated_db):
    gid = create_group(migrated_db, label=None, members=_members(("A", "M", "a")), now=1)
    add_members(migrated_db, link_group_id=gid, members=_members(("A", "M", "b"), ("A", "M", "c")))
    detail = get_group(migrated_db, gid)
    assert [m.entry_execution_id for m in detail.members] == ["a", "b", "c"]
    assert [m.ordinal for m in detail.members] == [0, 1, 2]


def test_add_duplicate_member_is_rejected(migrated_db):
    gid = create_group(migrated_db, label=None, members=_members(("A", "M", "a")), now=1)
    with pytest.raises(ValueError):
        add_members(migrated_db, link_group_id=gid, members=_members(("A", "M", "a")))


def test_remove_member(migrated_db):
    gid = create_group(
        migrated_db,
        label=None,
        members=_members(("A", "M", "a"), ("A", "M", "b")),
        now=1,
    )
    remove_member(
        migrated_db,
        link_group_id=gid,
        account="A",
        instrument="M",
        entry_execution_id="a",
    )
    detail = get_group(migrated_db, gid)
    assert [m.entry_execution_id for m in detail.members] == ["b"]


def test_delete_group_cascades_members(migrated_db):
    gid = create_group(migrated_db, label=None, members=_members(("A", "M", "a")), now=1)
    delete_group(migrated_db, gid)
    assert get_group(migrated_db, gid) is None
    conn = connect(migrated_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM position_links WHERE link_group_id = ?",
            (gid,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 0
