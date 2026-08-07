import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
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


@contextmanager
def transaction(path: Path | str) -> Iterator[sqlite3.Connection]:
    """connect -> BEGIN -> yield -> COMMIT; ROLLBACK on any BaseException; always close.

    The one canonical write-transaction shape for the whole app. Opens its
    own connection, so it must not be used for work that has to share a
    connection already held by the caller (e.g. ImportPipeline._run_tick).
    """
    conn = connect(path)
    try:
        conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


@contextmanager
def read_conn(path: Path | str) -> Iterator[sqlite3.Connection]:
    """connect -> yield -> close. For read-only access; no transaction."""
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def sql_placeholders(n: int) -> str:
    """Return "?,?,...,?" with n placeholders, for IN (...) clauses."""
    return ",".join("?" * n)
