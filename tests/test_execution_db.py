from db import connect
from models.execution import Execution
from services.execution_db import (
    EXECUTION_COLUMNS,
    execution_exists,
    execution_from_row,
    load_executions,
)
from services.import_db import bulk_insert_executions


def _ex(exid, account="Sim101", instrument="MNQ", ts=1, **overrides):
    base = dict(
        nt_execution_id=exid,
        account=account,
        instrument=instrument,
        timestamp=ts,
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
    base.update(overrides)
    return Execution(**base)


def _seed(db_path, executions):
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, executions)
    finally:
        conn.close()


def test_execution_columns_is_the_15_column_list():
    cols = [c.strip() for c in EXECUTION_COLUMNS.split(",")]
    assert cols == [
        "nt_execution_id",
        "account",
        "instrument",
        "timestamp",
        "side",
        "original_action",
        "quantity",
        "price",
        "commission",
        "entry_exit",
        "position_after",
        "source_order_id",
        "source_filename",
        "imported_at",
        "order_name",
    ]


def test_execution_from_row_round_trips(migrated_db):
    original = _ex("e1", source_order_id="o1", order_name="GateMktNextOpen")
    _seed(migrated_db, [original])
    conn = connect(migrated_db)
    try:
        row = conn.execute(f"SELECT {EXECUTION_COLUMNS} FROM executions").fetchone()
    finally:
        conn.close()
    assert execution_from_row(row) == original


def test_load_executions_unfiltered_orders_by_pair_then_time(migrated_db):
    _seed(
        migrated_db,
        [
            _ex("b2", account="Sim102", ts=5),
            _ex("a2", account="Sim101", ts=9),
            _ex("a1", account="Sim101", ts=3),
        ],
    )
    result = load_executions(migrated_db)
    assert [e.nt_execution_id for e in result] == ["a1", "a2", "b2"]


def test_load_executions_filters_by_account_and_instrument(migrated_db):
    _seed(
        migrated_db,
        [
            _ex("a1", account="Sim101", instrument="MNQ"),
            _ex("a2", account="Sim101", instrument="MES"),
            _ex("b1", account="Sim102", instrument="MNQ"),
        ],
    )
    result = load_executions(migrated_db, account="Sim101", instrument="MNQ")
    assert [e.nt_execution_id for e in result] == ["a1"]


def test_load_executions_filters_by_accounts_list(migrated_db):
    _seed(
        migrated_db,
        [
            _ex("a1", account="Sim101"),
            _ex("b1", account="Sim102"),
            _ex("c1", account="Sim103"),
        ],
    )
    result = load_executions(migrated_db, accounts=("Sim101", "Sim103"))
    assert [e.nt_execution_id for e in result] == ["a1", "c1"]


def test_load_executions_empty_accounts_means_no_filter(migrated_db):
    _seed(migrated_db, [_ex("a1"), _ex("b1", account="Sim102")])
    assert len(load_executions(migrated_db, accounts=())) == 2


def test_load_executions_rejects_account_and_accounts_together(migrated_db):
    import pytest

    with pytest.raises(ValueError):
        load_executions(migrated_db, account="Sim101", accounts=("Sim101",))


def test_execution_exists_strips_split_suffix(migrated_db):
    _seed(migrated_db, [_ex("e1")])
    assert execution_exists(migrated_db, "e1") is True
    assert execution_exists(migrated_db, "e1#close") is True
    assert execution_exists(migrated_db, "e1#open") is True
    assert execution_exists(migrated_db, "nope") is False
