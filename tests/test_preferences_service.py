from pathlib import Path

from db import connect
from migrations import run_migrations
from services.preferences import get_preference, set_preference


def _fresh_db(tmp_path: Path) -> Path:
    db = tmp_path / "app.db"
    conn = connect(db)
    try:
        run_migrations(conn, Path("migrations"))
    finally:
        conn.close()
    return db


def test_get_preference_returns_none_when_key_missing(tmp_path):
    db = _fresh_db(tmp_path)
    assert get_preference(db, "nope") is None


def test_set_then_get_roundtrip(tmp_path):
    db = _fresh_db(tmp_path)
    set_preference(db, "first_run_complete", "true")
    assert get_preference(db, "first_run_complete") == "true"


def test_set_preference_is_upsert(tmp_path):
    db = _fresh_db(tmp_path)
    set_preference(db, "k", "v1")
    set_preference(db, "k", "v2")
    assert get_preference(db, "k") == "v2"


def test_set_preference_with_none_deletes_key(tmp_path):
    db = _fresh_db(tmp_path)
    set_preference(db, "k", "v")
    set_preference(db, "k", None)
    assert get_preference(db, "k") is None
