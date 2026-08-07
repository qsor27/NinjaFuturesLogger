from services.preferences import get_preference, set_preference


def test_get_preference_returns_none_when_key_missing(migrated_db):
    db = migrated_db
    assert get_preference(db, "nope") is None


def test_set_then_get_roundtrip(migrated_db):
    db = migrated_db
    set_preference(db, "first_run_complete", "true")
    assert get_preference(db, "first_run_complete") == "true"


def test_set_preference_is_upsert(migrated_db):
    db = migrated_db
    set_preference(db, "k", "v1")
    set_preference(db, "k", "v2")
    assert get_preference(db, "k") == "v2"


def test_set_preference_with_none_deletes_key(migrated_db):
    db = migrated_db
    set_preference(db, "k", "v")
    set_preference(db, "k", None)
    assert get_preference(db, "k") is None
