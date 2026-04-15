import glob
import shutil
from pathlib import Path

from db import connect
from migrations import run_migrations


def test_009_purges_all_bars(tmp_path):
    """Stage migrations only through 008, insert a bar row, then apply 009."""
    db = tmp_path / "ftl.db"
    conn = connect(db)
    tmp_migrations = tmp_path / "migrations"
    tmp_migrations.mkdir()
    for f in sorted(glob.glob("migrations/0*.sql")):
        stem = Path(f).stem
        if stem > "008_instrument_coverage":
            continue
        shutil.copy(f, tmp_migrations / Path(f).name)
    run_migrations(conn, tmp_migrations)

    conn.execute(
        "INSERT INTO bars "
        "(instrument, timeframe, time, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('MNQ JUN26','1m',0,1,2,3,4,5,'yfinance',0)"
    )
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 1

    shutil.copy(
        "migrations/009_purge_mistagged_bars.sql",
        tmp_migrations / "009_purge_mistagged_bars.sql",
    )
    run_migrations(conn, tmp_migrations)
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 0


def test_009_is_idempotent(tmp_path):
    """After migration ran once, a newly inserted row must NOT be deleted
    on a subsequent run_migrations call (the migration is recorded in
    schema_migrations and skipped)."""
    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    conn.execute(
        "INSERT INTO bars "
        "(instrument, timeframe, time, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('MNQ JUN26','1m',0,1,2,3,4,5,'yfinance',0)"
    )
    run_migrations(conn, Path("migrations"))
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 1
