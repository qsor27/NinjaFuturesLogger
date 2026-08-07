"""Key-value user preferences backed by the user_preferences table.

All values are TEXT. Callers coerce to/from other types. A None value
deletes the row.
"""

import time
from pathlib import Path

from db import read_conn, transaction


def get_preference(db_path: Path | str, key: str) -> str | None:
    with read_conn(db_path) as conn:
        row = conn.execute("SELECT value FROM user_preferences WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def set_preference(db_path: Path | str, key: str, value: str | None) -> None:
    with transaction(db_path) as conn:
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
