from pathlib import Path
from zoneinfo import ZoneInfo

from services.import_pipeline import ImportPipeline
from tests.conftest import write_ninja_csv

TZ = ZoneInfo("America/Chicago")
ROW = (
    "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,swid,Entry,1 L,"
    "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
)


def test_scan_inbox_ticks_every_matching_file(tmp_path: Path, migrated_db: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    write_ninja_csv(inbox / "NinjaTrader_Executions_20260413.csv", [ROW])
    write_ninja_csv(inbox / "NinjaTrader_Executions_20260412.csv", [ROW.replace("swid", "swid2")])
    (inbox / "unrelated.txt").write_text("ignored", encoding="utf-8")

    pipeline = ImportPipeline(db_path=migrated_db, trader_tz=TZ)
    results = pipeline.scan_inbox(inbox)
    filenames = sorted(r.filename for r in results)
    assert filenames == [
        "NinjaTrader_Executions_20260412.csv",
        "NinjaTrader_Executions_20260413.csv",
    ]
    assert sum(r.rows_inserted for r in results) == 2


def test_scan_inbox_empty_directory(tmp_path: Path, migrated_db: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    pipeline = ImportPipeline(db_path=migrated_db, trader_tz=TZ)
    assert pipeline.scan_inbox(inbox) == []
