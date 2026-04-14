import tempfile
from pathlib import Path

from db import connect
from migrations import run_migrations
from services.chart_defaults import get_defaults, save_defaults


def _fresh_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = connect(Path(tmp.name))
    run_migrations(conn, Path("migrations"))
    conn.close()
    return Path(tmp.name)


def test_get_defaults_reads_seed_row():
    db_path = _fresh_db()
    result = get_defaults(db_path)
    assert result == {"default_timeframe": "5m", "volume_visible_default": True}


def test_get_defaults_returns_fresh_dict():
    db_path = _fresh_db()
    a = get_defaults(db_path)
    b = get_defaults(db_path)
    assert a == b
    assert a is not b
    a["default_timeframe"] = "XX"
    assert get_defaults(db_path)["default_timeframe"] == "5m"


def test_save_defaults_round_trip():
    db_path = _fresh_db()
    save_defaults(db_path, default_timeframe="1m", volume_visible_default=False)
    result = get_defaults(db_path)
    assert result == {"default_timeframe": "1m", "volume_visible_default": False}


def test_save_defaults_updates_updated_at():
    db_path = _fresh_db()
    conn = connect(db_path)
    try:
        initial_ts = conn.execute(
            "SELECT updated_at FROM chart_defaults WHERE id=1"
        ).fetchone()[0]
    finally:
        conn.close()
    save_defaults(db_path, default_timeframe="15m", volume_visible_default=True)
    conn = connect(db_path)
    try:
        new_ts = conn.execute(
            "SELECT updated_at FROM chart_defaults WHERE id=1"
        ).fetchone()[0]
    finally:
        conn.close()
    assert new_ts >= initial_ts
