from pathlib import Path
from zoneinfo import ZoneInfo

from db import connect
from services.import_pipeline import ImportPipeline

TZ = ZoneInfo("America/Chicago")

HEADER = (
    "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
    "Commission,Rate,Account,Connection,TradeValidation\n"
)
ROW1 = (
    "MNQ,Buy,3,4237.75,1/15/2025 2:45:30 PM,abc123,Entry,3 L,"
    "12345,Manual Entry,$5.00,1,Sim101,Apex Trader Funding ,\n"
)
ROW2 = (
    "MNQ,Sell,3,4240.00,1/15/2025 3:00:00 PM,abc124,Exit,-,"
    "12346,Manual Exit,$5.00,1,Sim101,Apex Trader Funding ,\n"
)
BAD_ROW = (
    "MNQ,Teleport,1,4000,1/15/2025 2:45:30 PM,badid,Entry,1 L,"
    "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
)


def _pipeline(db_path: Path, hooks=None):
    return ImportPipeline(
        db_path=db_path,
        trader_tz=TZ,
        post_tick_hooks=hooks or [],
    )


def _count_executions(db_path: Path) -> int:
    conn = connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
    finally:
        conn.close()


def test_first_tick_drops_header_and_inserts_rows(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1 + ROW2, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    result = pipeline.ingest_tick(path)
    assert result.status == "ok"
    assert result.rows_parsed == 2
    assert result.rows_inserted == 2
    assert result.rows_skipped_duplicate == 0
    assert result.rows_rejected == 0
    assert _count_executions(migrated_db) == 2


def test_second_tick_is_noop_when_file_unchanged(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    pipeline.ingest_tick(path)
    result = pipeline.ingest_tick(path)
    assert result.lines_read == 0
    assert result.rows_inserted == 0
    assert _count_executions(migrated_db) == 1


def test_tick_resumes_from_cursor_when_rows_are_appended(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    pipeline.ingest_tick(path)
    with path.open("a", encoding="utf-8") as f:
        f.write(ROW2)
    result = pipeline.ingest_tick(path)
    assert result.rows_parsed == 1
    assert result.rows_inserted == 1
    assert _count_executions(migrated_db) == 2


def test_tick_ignores_trailing_partial_line(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1 + "MNQ,Buy,3", encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    result = pipeline.ingest_tick(path)
    assert result.rows_inserted == 1
    with path.open("a", encoding="utf-8") as f:
        f.write(",4240.00,1/15/2025 3:00:00 PM,zid,Exit,-,"
                "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n")
    result = pipeline.ingest_tick(path)
    assert result.rows_inserted == 1
    assert _count_executions(migrated_db) == 2


def test_tick_returns_partial_when_no_newline_seen_yet(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text("Instrument,Action,", encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    result = pipeline.ingest_tick(path)
    assert result.status == "partial"
    assert result.rows_inserted == 0


def test_tick_records_reject_rows(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1 + BAD_ROW, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    result = pipeline.ingest_tick(path)
    assert result.rows_parsed == 1
    assert result.rows_rejected == 1
    conn = connect(migrated_db)
    try:
        rejects = conn.execute(
            "SELECT reason FROM import_rejects WHERE tick_id = ?",
            (result.tick_id,),
        ).fetchall()
        assert len(rejects) == 1
        assert "action" in rejects[0]["reason"]
    finally:
        conn.close()


def test_tick_shrinking_file_resets_cursor(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1 + ROW2, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    pipeline.ingest_tick(path)
    path.write_text(HEADER + ROW1, encoding="utf-8")
    result = pipeline.ingest_tick(path)
    assert result.rows_inserted == 0
    assert result.rows_skipped_duplicate == 1


def test_tick_records_row_in_import_runs(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    result = pipeline.ingest_tick(path)
    conn = connect(migrated_db)
    try:
        row = conn.execute(
            "SELECT filename, status, rows_inserted, cursor_before, cursor_after "
            "FROM import_runs WHERE tick_id = ?",
            (result.tick_id,),
        ).fetchone()
        assert row["filename"] == path.name
        assert row["status"] == "ok"
        assert row["rows_inserted"] == 1
        assert row["cursor_before"] == 0
        assert row["cursor_after"] > 0
    finally:
        conn.close()


def test_post_tick_hook_fires_after_commit(tmp_path: Path, migrated_db: Path):
    calls = []

    def hook(result, parsed, affected):
        calls.append((result.rows_inserted, len(parsed), affected))

    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1, encoding="utf-8")
    pipeline = _pipeline(migrated_db, hooks=[hook])
    pipeline.ingest_tick(path)
    assert len(calls) == 1
    rows_inserted, parsed_count, affected = calls[0]
    assert rows_inserted == 1
    assert parsed_count == 1
    assert ("Sim101", "MNQ") in affected


def test_post_tick_hook_exception_does_not_break_tick(tmp_path: Path, migrated_db: Path):
    def bad_hook(*_a, **_kw):
        raise RuntimeError("boom")

    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1, encoding="utf-8")
    pipeline = _pipeline(migrated_db, hooks=[bad_hook])
    result = pipeline.ingest_tick(path)
    assert result.rows_inserted == 1
