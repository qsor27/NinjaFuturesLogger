from pathlib import Path

from db import connect
from migrations import run_migrations
from models.execution import Execution, RejectRecord
from services.import_db import (
    bulk_insert_executions,
    delete_cursor,
    delete_executions,
    get_cursor,
    insert_rejects,
    record_run,
    save_cursor,
)


def _migrated(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def _ex(i: int, account: str = "Sim101"):
    return Execution(
        nt_execution_id=f"id-{i}",
        account=account,
        instrument="MNQ",
        timestamp=1_700_000_000 + i,
        side="Buy",
        original_action="Buy",
        quantity=1,
        price=4000.0 + i,
        commission=0.0,
        entry_exit="Entry",
        position_after=f"{i} L",
        source_order_id=None,
        source_filename="file.csv",
        imported_at=1_700_000_100,
    )


def test_cursor_lifecycle(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        assert get_cursor(conn, "file.csv") is None
        save_cursor(conn, "file.csv", byte_offset=123, file_mtime=456)
        assert get_cursor(conn, "file.csv") == 123
        save_cursor(conn, "file.csv", byte_offset=456, file_mtime=789)
        assert get_cursor(conn, "file.csv") == 456
        delete_cursor(conn, "file.csv")
        assert get_cursor(conn, "file.csv") is None
    finally:
        conn.close()


def test_bulk_insert_counts_inserted_and_skipped(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        rows = [_ex(1), _ex(2), _ex(3)]
        inserted, skipped = bulk_insert_executions(conn, rows)
        assert inserted == 3
        assert skipped == 0
        inserted, skipped = bulk_insert_executions(conn, rows)
        assert inserted == 0
        assert skipped == 3
        inserted, skipped = bulk_insert_executions(conn, [_ex(2), _ex(4)])
        assert inserted == 1
        assert skipped == 1
    finally:
        conn.close()


def test_bulk_insert_empty_list_is_noop(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        inserted, skipped = bulk_insert_executions(conn, [])
        assert (inserted, skipped) == (0, 0)
    finally:
        conn.close()


def test_record_run_and_insert_rejects(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        tick_id = record_run(
            conn,
            filename="file.csv",
            started_at=100,
            finished_at=101,
            cursor_before=0,
            cursor_after=500,
            lines_read=3,
            rows_parsed=2,
            rows_inserted=2,
            rows_skipped_duplicate=0,
            rows_rejected=1,
            status="ok",
            error=None,
        )
        assert isinstance(tick_id, int) and tick_id > 0
        insert_rejects(
            conn,
            tick_id,
            [RejectRecord(line_number=3, raw_line="oops", reason="bad cols")],
        )
        row = conn.execute(
            "SELECT filename, status, rows_inserted FROM import_runs WHERE tick_id=?",
            (tick_id,),
        ).fetchone()
        assert row["filename"] == "file.csv"
        assert row["status"] == "ok"
        assert row["rows_inserted"] == 2
        rej = conn.execute(
            "SELECT line_number, raw_line, reason FROM import_rejects WHERE tick_id=?",
            (tick_id,),
        ).fetchall()
        assert len(rej) == 1
        assert rej[0]["line_number"] == 3
    finally:
        conn.close()


def test_delete_executions_removes_only_matches(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        bulk_insert_executions(conn, [_ex(1), _ex(2), _ex(3)])
        deleted = delete_executions(conn, ["id-1", "id-3"])
        assert deleted == 2
        remaining = [
            r[0] for r in conn.execute(
                "SELECT nt_execution_id FROM executions ORDER BY nt_execution_id"
            ).fetchall()
        ]
        assert remaining == ["id-2"]
    finally:
        conn.close()


def test_delete_executions_empty_list(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        assert delete_executions(conn, []) == 0
    finally:
        conn.close()
