from services.notes import (
    delete_note,
    get_note,
    list_notes_for_executions,
    strip_split_suffix,
    upsert_note,
)
from tests.conftest import make_execution, seed_executions


def test_strip_split_suffix_handles_open_and_close():
    assert strip_split_suffix("abc") == "abc"
    assert strip_split_suffix("abc#open") == "abc"
    assert strip_split_suffix("abc#close") == "abc"
    assert strip_split_suffix("abc#xyz") == "abc#xyz"  # unknown suffix passes through


def test_get_note_missing_returns_none(migrated_db):
    seed_executions(migrated_db, [make_execution("abc")])
    assert get_note(migrated_db, "abc") is None


def test_upsert_note_inserts_then_updates(migrated_db):
    seed_executions(migrated_db, [make_execution("abc")])
    upsert_note(migrated_db, execution_id="abc", note="first", now=100)
    assert get_note(migrated_db, "abc") == {"note": "first", "updated_at": 100}
    upsert_note(migrated_db, execution_id="abc", note="second", now=200)
    assert get_note(migrated_db, "abc") == {"note": "second", "updated_at": 200}


def test_upsert_note_strips_split_suffix(migrated_db):
    seed_executions(migrated_db, [make_execution("abc")])
    upsert_note(migrated_db, execution_id="abc#open", note="split", now=50)
    assert get_note(migrated_db, "abc") == {"note": "split", "updated_at": 50}
    assert get_note(migrated_db, "abc#open") == {"note": "split", "updated_at": 50}


def test_delete_note(migrated_db):
    seed_executions(migrated_db, [make_execution("abc")])
    upsert_note(migrated_db, execution_id="abc", note="x", now=1)
    delete_note(migrated_db, "abc")
    assert get_note(migrated_db, "abc") is None


def test_list_notes_for_executions_batches(migrated_db):
    seed_executions(migrated_db, [make_execution("a"), make_execution("b"), make_execution("c")])
    upsert_note(migrated_db, execution_id="a", note="alpha", now=1)
    upsert_note(migrated_db, execution_id="c", note="gamma", now=3)
    notes = list_notes_for_executions(migrated_db, ["a", "b", "c#close"])
    assert notes == {"a": "alpha", "c": "gamma"}


def test_upsert_note_on_nonexistent_execution_raises(migrated_db):
    try:
        upsert_note(migrated_db, execution_id="missing", note="x", now=1)
        raised = False
    except Exception:
        raised = True
    assert raised
