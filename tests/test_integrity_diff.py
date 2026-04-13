from pathlib import Path

from db import connect
from models.execution import Execution
from services.import_db import bulk_insert_executions
from services.integrity import run_integrity_diff
from services.integrity_db import list_open_for_pair


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


def test_diff_inserts_new_issue(migrated_db: Path):
    conn = connect(migrated_db)
    try:
        bulk_insert_executions(
            conn,
            [
                _ex("e1", "Buy", 1, 100, position_after="5 L"),
            ],
        )
    finally:
        conn.close()
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    conn = connect(migrated_db)
    try:
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        assert len(rows) == 1
        assert rows[0]["execution_id"] == "e1"
    finally:
        conn.close()


def test_diff_auto_resolves_stale_issue_when_data_is_fixed(migrated_db: Path):
    conn = connect(migrated_db)
    try:
        bulk_insert_executions(
            conn,
            [
                _ex("e1", "Buy", 1, 100, position_after="5 L"),
            ],
        )
    finally:
        conn.close()
    run_integrity_diff(migrated_db, "Sim101", "MNQ")

    conn = connect(migrated_db)
    try:
        conn.execute("DELETE FROM executions")
        bulk_insert_executions(
            conn,
            [
                _ex("e1", "Buy", 1, 100, position_after="1 L"),
            ],
        )
    finally:
        conn.close()
    run_integrity_diff(migrated_db, "Sim101", "MNQ")

    conn = connect(migrated_db)
    try:
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        assert rows == []
        resolved = conn.execute(
            "SELECT resolved_by FROM integrity_issues WHERE execution_id='e1'"
        ).fetchone()
        assert resolved["resolved_by"] == "system"
    finally:
        conn.close()


def test_diff_is_idempotent_when_issue_persists(migrated_db: Path):
    conn = connect(migrated_db)
    try:
        bulk_insert_executions(
            conn,
            [
                _ex("e1", "Buy", 1, 100, position_after="5 L"),
            ],
        )
    finally:
        conn.close()
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    conn = connect(migrated_db)
    try:
        rows = conn.execute(
            "SELECT COUNT(*) FROM integrity_issues WHERE execution_id='e1'"
        ).fetchone()[0]
        assert rows == 1
    finally:
        conn.close()


def test_diff_leaves_other_pairs_alone(migrated_db: Path):
    conn = connect(migrated_db)
    try:
        bulk_insert_executions(
            conn,
            [
                Execution(
                    nt_execution_id="e1",
                    account="Sim101",
                    instrument="MNQ",
                    timestamp=100,
                    side="Buy",
                    original_action="Buy",
                    quantity=1,
                    price=4000.0,
                    commission=0.0,
                    entry_exit="Entry",
                    position_after="5 L",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=100,
                ),
                Execution(
                    nt_execution_id="e2",
                    account="APEX-1",
                    instrument="ES",
                    timestamp=100,
                    side="Buy",
                    original_action="Buy",
                    quantity=1,
                    price=4000.0,
                    commission=0.0,
                    entry_exit="Entry",
                    position_after="5 L",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=100,
                ),
            ],
        )
    finally:
        conn.close()
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    conn = connect(migrated_db)
    try:
        sim = list_open_for_pair(conn, "Sim101", "MNQ")
        apex = list_open_for_pair(conn, "APEX-1", "ES")
        assert len(sim) == 1
        assert apex == []
    finally:
        conn.close()
