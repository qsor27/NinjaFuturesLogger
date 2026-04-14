from pathlib import Path

from db import connect
from models.browsing import LinkGroup, LinkGroupDetail, LinkMember


def create_group(
    db_path: Path | str,
    *,
    label: str | None,
    members: list[LinkMember],
    now: int,
) -> int:
    """Create a link group and populate its members. Returns the new
    link_group_id. Raises ValueError on empty or duplicate-member input."""
    if not members:
        raise ValueError("link group must have at least one member")
    seen: set[tuple[str, str, str]] = set()
    for m in members:
        key = (m.account, m.instrument, m.entry_execution_id)
        if key in seen:
            raise ValueError(f"duplicate member: {key}")
        seen.add(key)

    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        try:
            cur = conn.execute(
                "INSERT INTO link_groups (label, created_at) VALUES (?, ?)",
                (label, now),
            )
            gid = int(cur.lastrowid)
            for ordinal, m in enumerate(members):
                conn.execute(
                    "INSERT INTO position_links "
                    "(link_group_id, account, instrument, entry_execution_id, ordinal) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (gid, m.account, m.instrument, m.entry_execution_id, ordinal),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return gid


def get_group(db_path: Path | str, link_group_id: int) -> LinkGroupDetail | None:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT link_group_id, label, created_at FROM link_groups " "WHERE link_group_id = ?",
            (link_group_id,),
        ).fetchone()
        if row is None:
            return None
        member_rows = conn.execute(
            "SELECT account, instrument, entry_execution_id, ordinal "
            "FROM position_links WHERE link_group_id = ? ORDER BY ordinal",
            (link_group_id,),
        ).fetchall()
    finally:
        conn.close()
    return LinkGroupDetail(
        link_group_id=int(row["link_group_id"]),
        label=row["label"],
        created_at=int(row["created_at"]),
        members=[
            LinkMember(
                account=r["account"],
                instrument=r["instrument"],
                entry_execution_id=r["entry_execution_id"],
                ordinal=int(r["ordinal"]),
            )
            for r in member_rows
        ],
    )


def list_groups(db_path: Path | str) -> list[LinkGroup]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT link_group_id, label, created_at " "FROM link_groups ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [
        LinkGroup(
            link_group_id=int(r["link_group_id"]),
            label=r["label"],
            created_at=int(r["created_at"]),
        )
        for r in rows
    ]


def rename_group(
    db_path: Path | str,
    *,
    link_group_id: int,
    label: str | None,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "UPDATE link_groups SET label = ? WHERE link_group_id = ?",
                (label, link_group_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def add_members(
    db_path: Path | str,
    *,
    link_group_id: int,
    members: list[LinkMember],
) -> None:
    if not members:
        return
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        try:
            existing = conn.execute(
                "SELECT account, instrument, entry_execution_id, ordinal "
                "FROM position_links WHERE link_group_id = ?",
                (link_group_id,),
            ).fetchall()
            existing_keys = {
                (r["account"], r["instrument"], r["entry_execution_id"]) for r in existing
            }
            next_ordinal = max((int(r["ordinal"]) for r in existing), default=-1) + 1
            for m in members:
                key = (m.account, m.instrument, m.entry_execution_id)
                if key in existing_keys:
                    raise ValueError(f"duplicate member: {key}")
                conn.execute(
                    "INSERT INTO position_links "
                    "(link_group_id, account, instrument, entry_execution_id, ordinal) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (link_group_id, m.account, m.instrument, m.entry_execution_id, next_ordinal),
                )
                existing_keys.add(key)
                next_ordinal += 1
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def remove_member(
    db_path: Path | str,
    *,
    link_group_id: int,
    account: str,
    instrument: str,
    entry_execution_id: str,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "DELETE FROM position_links "
                "WHERE link_group_id = ? AND account = ? "
                "  AND instrument = ? AND entry_execution_id = ?",
                (link_group_id, account, instrument, entry_execution_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def delete_group(db_path: Path | str, link_group_id: int) -> None:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "DELETE FROM link_groups WHERE link_group_id = ?",
                (link_group_id,),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
