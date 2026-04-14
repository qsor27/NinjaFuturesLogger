from db import connect
from models.execution import Execution
from services.flags import get_flag, list_flags_for_executions, set_reviewed
from services.import_db import bulk_insert_executions


def _ex(exid="abc"):
    return Execution(
        nt_execution_id=exid,
        account="Sim101",
        instrument="MNQ",
        timestamp=1,
        side="Buy",
        original_action="Buy",
        quantity=1,
        price=100.0,
        commission=0.0,
        entry_exit="Entry",
        position_after="1 L",
        source_order_id=None,
        source_filename="f.csv",
        imported_at=1,
    )


def _seed(db_path, executions):
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, executions)
    finally:
        conn.close()


def test_get_flag_missing_returns_default(migrated_db):
    _seed(migrated_db, [_ex()])
    assert get_flag(migrated_db, "abc") == {"reviewed": False, "reviewed_at": None}


def test_set_reviewed_true_then_false(migrated_db):
    _seed(migrated_db, [_ex()])
    set_reviewed(migrated_db, execution_id="abc", reviewed=True, now=100)
    assert get_flag(migrated_db, "abc") == {"reviewed": True, "reviewed_at": 100}
    set_reviewed(migrated_db, execution_id="abc", reviewed=False, now=200)
    assert get_flag(migrated_db, "abc") == {"reviewed": False, "reviewed_at": 200}


def test_set_reviewed_strips_split_suffix(migrated_db):
    _seed(migrated_db, [_ex(exid="abc")])
    set_reviewed(migrated_db, execution_id="abc#open", reviewed=True, now=50)
    assert get_flag(migrated_db, "abc") == {"reviewed": True, "reviewed_at": 50}


def test_list_flags_for_executions_batches(migrated_db):
    _seed(migrated_db, [_ex(exid="a"), _ex(exid="b"), _ex(exid="c")])
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
