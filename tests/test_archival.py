from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from db import connect
from services.import_db import get_cursor, save_cursor
from services.import_pipeline import ImportPipeline

TZ = ZoneInfo("America/Chicago")


def _pipeline(db_path: Path):
    return ImportPipeline(db_path=db_path, trader_tz=TZ)


def test_archive_moves_older_files_only(tmp_path: Path, migrated_db: Path):
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    inbox.mkdir()
    yesterday = inbox / "NinjaTrader_Executions_20260412.csv"
    today = inbox / "NinjaTrader_Executions_20260413.csv"
    yesterday.write_text("", encoding="utf-8")
    today.write_text("", encoding="utf-8")

    conn = connect(migrated_db)
    try:
        save_cursor(conn, yesterday.name, byte_offset=0, file_mtime=0)
    finally:
        conn.close()

    pipeline = _pipeline(migrated_db)
    moved = pipeline.archive_completed_sessions(
        inbox_dir=inbox,
        archive_dir=archive,
        current_trade_date=date(2026, 4, 13),
    )

    assert len(moved) == 1
    assert not yesterday.exists()
    assert today.exists()
    expected = archive / "2026-04-12" / yesterday.name
    assert expected.exists()

    conn = connect(migrated_db)
    try:
        assert get_cursor(conn, yesterday.name) is None
    finally:
        conn.close()


def test_archive_ignores_nonmatching_filenames(tmp_path: Path, migrated_db: Path):
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    inbox.mkdir()
    (inbox / "random.csv").write_text("", encoding="utf-8")
    (inbox / "NinjaTrader_Executions_notadate.csv").write_text("", encoding="utf-8")

    pipeline = _pipeline(migrated_db)
    moved = pipeline.archive_completed_sessions(
        inbox_dir=inbox,
        archive_dir=archive,
        current_trade_date=date(2026, 4, 13),
    )
    assert moved == []
    assert (inbox / "random.csv").exists()
    assert (inbox / "NinjaTrader_Executions_notadate.csv").exists()
