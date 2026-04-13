import sqlite3
from pathlib import Path


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection with the project's standard pragmas.

    WAL gives readers concurrent access alongside the background writer.
    `foreign_keys=ON` is required because every cascade in the schema relies
    on it; SQLite ships with foreign keys *off* by default.

    One connection per thread. Do not share connections across threads.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        detect_types=sqlite3.PARSE_DECLTYPES,
        isolation_level=None,  # autocommit; we manage transactions explicitly
    )
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn
