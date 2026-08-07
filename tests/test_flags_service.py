from services.flags import get_flag, list_flags_for_executions, set_reviewed
from tests.conftest import make_execution, seed_executions


def test_get_flag_missing_returns_default(migrated_db):
    seed_executions(migrated_db, [make_execution("abc")])
    assert get_flag(migrated_db, "abc") == {"reviewed": False, "reviewed_at": None}


def test_set_reviewed_true_then_false(migrated_db):
    seed_executions(migrated_db, [make_execution("abc")])
    set_reviewed(migrated_db, execution_id="abc", reviewed=True, now=100)
    assert get_flag(migrated_db, "abc") == {"reviewed": True, "reviewed_at": 100}
    set_reviewed(migrated_db, execution_id="abc", reviewed=False, now=200)
    assert get_flag(migrated_db, "abc") == {"reviewed": False, "reviewed_at": 200}


def test_set_reviewed_strips_split_suffix(migrated_db):
    seed_executions(migrated_db, [make_execution("abc")])
    set_reviewed(migrated_db, execution_id="abc#open", reviewed=True, now=50)
    assert get_flag(migrated_db, "abc") == {"reviewed": True, "reviewed_at": 50}


def test_list_flags_for_executions_batches(migrated_db):
    seed_executions(migrated_db, [make_execution("a"), make_execution("b"), make_execution("c")])
    set_reviewed(migrated_db, execution_id="a", reviewed=True, now=1)
    set_reviewed(migrated_db, execution_id="c", reviewed=True, now=3)
    flags = list_flags_for_executions(migrated_db, ["a", "b", "c#close"])
    assert flags == {"a": True, "c": True}


def test_set_reviewed_on_nonexistent_raises(migrated_db):
    raised = False
    try:
        set_reviewed(migrated_db, execution_id="missing", reviewed=True, now=1)
    except Exception:
        raised = True
    assert raised
