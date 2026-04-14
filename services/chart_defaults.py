"""Chart default settings — DB-backed (plan 16).

get_defaults(db_path) reads the single `chart_defaults` row (id=1, enforced by
the migration CHECK constraint). save_defaults() writes that row. The
frontend pickup helper calls get_defaults() once per chart mount; plan 16's
/settings/chart page calls save_defaults() on form submit.

DEFAULT_TIMEFRAME and VOLUME_VISIBLE_DEFAULT remain as defensive fallbacks
if the row is somehow missing (the migration inserts it in the same
transaction as CREATE TABLE, so this only matters in tests that skip
migrations).
"""

import time
from pathlib import Path

from db import connect

DEFAULT_TIMEFRAME = "5m"
VOLUME_VISIBLE_DEFAULT = True


def get_defaults(db_path: Path | str) -> dict:
    """Return a fresh dict with the current chart defaults."""
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT default_timeframe, volume_visible_default FROM chart_defaults WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {
            "default_timeframe": DEFAULT_TIMEFRAME,
            "volume_visible_default": VOLUME_VISIBLE_DEFAULT,
        }
    return {
        "default_timeframe": row["default_timeframe"],
        "volume_visible_default": bool(row["volume_visible_default"]),
    }


def save_defaults(
    db_path: Path | str,
    *,
    default_timeframe: str,
    volume_visible_default: bool,
) -> None:
    if default_timeframe not in ("1m", "5m", "15m", "1h", "4h", "1d"):
        raise ValueError(f"invalid default_timeframe: {default_timeframe!r}")
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "UPDATE chart_defaults SET default_timeframe = ?, "
                "volume_visible_default = ?, updated_at = ? WHERE id = 1",
                (default_timeframe, int(bool(volume_visible_default)), int(time.time())),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
