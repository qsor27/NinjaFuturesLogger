from pathlib import Path

from db import connect
from migrations import run_migrations
from models.position import IntegrityIssue
from services.integrity_db import (
    auto_resolve_missing,
    list_open_for_pair,
    mark_ignored,
    mark_resolved_by_user,
    upsert_issue,
)


def _migrated(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def _issue(eid: str = "abc"):
    return IntegrityIssue(
        account="Sim101",
        instrument="MNQ",
        execution_id=eid,
        severity="high",
        type="position_column_mismatch",
        description="mismatch",
    )


def test_upsert_new_issue_inserts_row(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue(), now=100)
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        assert len(rows) == 1
        assert rows[0]["execution_id"] == "abc"
        assert rows[0]["detected_at"] == 100
        assert rows[0]["last_seen_at"] == 100
        assert rows[0]["resolved_at"] is None
    finally:
        conn.close()


def test_upsert_same_issue_bumps_last_seen(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue(), now=100)
        upsert_issue(conn, _issue(), now=200)
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        assert len(rows) == 1
        assert rows[0]["detected_at"] == 100
        assert rows[0]["last_seen_at"] == 200
    finally:
        conn.close()


def test_auto_resolve_missing_resolves_only_stale_issues(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue("abc"), now=100)
        upsert_issue(conn, _issue("xyz"), now=100)
        auto_resolve_missing(
            conn,
            account="Sim101",
            instrument="MNQ",
            present_keys={("abc", "position_column_mismatch")},
            now=200,
        )
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        ids = {r["execution_id"] for r in rows}
        assert ids == {"abc"}
        xyz = conn.execute(
            "SELECT resolved_at, resolved_by FROM integrity_issues WHERE execution_id='xyz'"
        ).fetchone()
        assert xyz["resolved_at"] == 200
        assert xyz["resolved_by"] == "system"
    finally:
        conn.close()


def test_auto_resolve_skips_ignored_issues(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue("abc"), now=100)
        mark_ignored(conn, issue_id=1, note="known false positive")
        auto_resolve_missing(
            conn,
            account="Sim101",
            instrument="MNQ",
            present_keys=set(),
            now=200,
        )
        row = conn.execute(
            "SELECT ignored, resolved_at FROM integrity_issues WHERE issue_id=1"
        ).fetchone()
        assert row["ignored"] == 1
        assert row["resolved_at"] is None
    finally:
        conn.close()


def test_mark_resolved_by_user(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue(), now=100)
        mark_resolved_by_user(conn, issue_id=1, now=150, note="fixed by hand")
        row = conn.execute(
            "SELECT resolved_at, resolved_by, resolution_note "
            "FROM integrity_issues WHERE issue_id=1"
        ).fetchone()
        assert row["resolved_at"] == 150
        assert row["resolved_by"] == "user"
        assert row["resolution_note"] == "fixed by hand"
    finally:
        conn.close()


def test_list_open_excludes_resolved_and_ignored(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue("a"), now=100)
        upsert_issue(conn, _issue("b"), now=100)
        upsert_issue(conn, _issue("c"), now=100)
        mark_resolved_by_user(conn, issue_id=1, now=110, note=None)
        mark_ignored(conn, issue_id=2, note="noise")
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        ids = {r["execution_id"] for r in rows}
        assert ids == {"c"}
    finally:
        conn.close()
