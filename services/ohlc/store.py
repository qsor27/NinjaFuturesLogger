import sqlite3
import time
from collections.abc import Sequence

from models.bar import Bar


def insert_many(conn: sqlite3.Connection, bars: Sequence[Bar]) -> int:
    """UPSERT bars on (instrument, timeframe, time). Returns rows affected.

    Re-fetching an existing range cleanly rewrites it; whichever source
    last wrote the row wins. Keep this transactional decision at the
    *caller*: the fetcher wraps a single tick's writes in BEGIN/COMMIT.
    """
    if not bars:
        return 0
    fetched_at = int(time.time())
    rows = [
        (
            b.instrument,
            b.timeframe,
            b.time,
            b.open,
            b.high,
            b.low,
            b.close,
            b.volume,
            b.source,
            fetched_at,
        )
        for b in bars
    ]
    cur = conn.executemany(
        "INSERT INTO bars "
        "(instrument, timeframe, time, open, high, low, close, volume, source, fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(instrument, timeframe, time) DO UPDATE SET "
        " open = excluded.open,"
        " high = excluded.high,"
        " low = excluded.low,"
        " close = excluded.close,"
        " volume = excluded.volume,"
        " source = excluded.source,"
        " fetched_at = excluded.fetched_at",
        rows,
    )
    return cur.rowcount or 0


def read_range(
    conn: sqlite3.Connection,
    *,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> list[Bar]:
    """Return bars in [start, end) ordered by time."""
    rows = conn.execute(
        "SELECT instrument, timeframe, time, open, high, low, close, volume, source "
        "FROM bars WHERE instrument = ? AND timeframe = ? "
        "  AND time >= ? AND time < ? "
        "ORDER BY time",
        (instrument, timeframe, start, end),
    ).fetchall()
    return [
        Bar(
            instrument=r["instrument"],
            timeframe=r["timeframe"],
            time=r["time"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
            source=r["source"],
        )
        for r in rows
    ]


def list_times(
    conn: sqlite3.Connection,
    *,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> list[int]:
    """Return the sorted list of bar timestamps in [start, end)."""
    rows = conn.execute(
        "SELECT time FROM bars WHERE instrument = ? AND timeframe = ? "
        "  AND time >= ? AND time < ? ORDER BY time",
        (instrument, timeframe, start, end),
    ).fetchall()
    return [int(r["time"]) for r in rows]
