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

from db import read_conn, transaction
from models.settings import VALID_TIMEFRAMES

DEFAULT_TIMEFRAME = "5m"
VOLUME_VISIBLE_DEFAULT = True


def get_defaults(db_path: Path | str) -> dict:
    """Return a fresh dict with the current chart defaults."""
    with read_conn(db_path) as conn:
        row = conn.execute(
            "SELECT default_timeframe, volume_visible_default FROM chart_defaults WHERE id = 1"
        ).fetchone()
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
    if default_timeframe not in VALID_TIMEFRAMES:
        raise ValueError(f"invalid default_timeframe: {default_timeframe!r}")
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE chart_defaults SET default_timeframe = ?, "
            "volume_visible_default = ?, updated_at = ? WHERE id = 1",
            (default_timeframe, int(bool(volume_visible_default)), int(time.time())),
        )
