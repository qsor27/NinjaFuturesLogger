"""Key-value user preferences backed by the user_preferences table.

All values are TEXT. Callers coerce to/from other types. A None value
deletes the row.
"""

import time
from pathlib import Path

from db import connect


def get_preference(db_path: Path | str, key: str) -> str | None:
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT value FROM user_preferences WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return None if row is None else row["value"]


def set_preference(db_path: Path | str, key: str, value: str | None) -> None:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        try:
            if value is None:
                conn.execute("DELETE FROM user_preferences WHERE key = ?", (key,))
            else:
                conn.execute(
                    "INSERT INTO user_preferences (key, value, updated_at) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET "
                    "  value = excluded.value, updated_at = excluded.updated_at",
                    (key, value, int(time.time())),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
