from db import connect
from models.execution import Execution
from services.flags import set_reviewed
from services.import_db import bulk_insert_executions
from services.notes import upsert_note
from services.position_filters import PositionFilter
from services.positions_service import (
    attach_metadata,
    get_filter_options,
    list_positions_page,
)


def _ex(exid, account, instrument, ts, side="Buy", action="Buy", ex_mark="Entry", pos_col="1 L"):
    return Execution(
        nt_execution_id=exid,
        account=account,
        instrument=instrument,
        timestamp=ts,
        side=side,
        original_action=action,
        quantity=1,
        price=100.0,
        commission=0.0,
        entry_exit=ex_mark,
        position_after=pos_col,
        source_order_id=None,
        source_filename="f.csv",
        imported_at=ts,
    )


def _seed(db_path, execs):
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, execs)
    finally:
        conn.close()


def test_list_positions_page_basic(migrated_db):
    _seed(
        migrated_db,
        [
            _ex("a", "Sim101", "MNQ", 100, "Buy", "Buy", "Entry", "1 L"),
            _ex("b", "Sim101", "MNQ", 200, "Sell", "Sell", "Exit", "-"),
            _ex("c", "Sim101", "MNQ", 300, "Buy", "Buy", "Entry", "1 L"),
            _ex("d", "Sim101", "MNQ", 400, "Sell", "Sell", "Exit", "-"),
        ],
    )
    result = list_positions_page(
        migrated_db,
        filter_=PositionFilter(),
        page=1,
        page_size=50,
    )
    assert result.page.total == 2
    assert result.page.page == 1
    assert [p.entry_execution_id for p in result.positions] == ["c", "a"]  # newest-first


def test_list_positions_page_account_filter(migrated_db):
    _seed(
        migrated_db,
        [
            _ex("a", "X", "MNQ", 100, "Buy", "Buy", "Entry", "1 L"),
            _ex("b", "X", "MNQ", 200, "Sell", "Sell", "Exit", "-"),
            _ex("c", "Y", "MNQ", 300, "Buy", "Buy", "Entry", "1 L"),
            _ex("d", "Y", "MNQ", 400, "Sell", "Sell", "Exit", "-"),
        ],
    )
    result = list_positions_page(
        migrated_db,
        filter_=PositionFilter(account="X"),
        page=1,
        page_size=50,
    )
    assert result.page.total == 1
    assert result.positions[0].account == "X"


def test_list_positions_page_pagination(migrated_db):
    executions = []
    for i in range(6):
        entry_id = f"e{i}"
        exit_id = f"x{i}"
        executions.append(_ex(entry_id, "A", "MNQ", 100 + i * 10, "Buy", "Buy", "Entry", "1 L"))
        executions.append(_ex(exit_id, "A", "MNQ", 105 + i * 10, "Sell", "Sell", "Exit", "-"))
    _seed(migrated_db, executions)
    page1 = list_positions_page(migrated_db, filter_=PositionFilter(), page=1, page_size=2)
    page2 = list_positions_page(migrated_db, filter_=PositionFilter(), page=2, page_size=2)
    assert page1.page.total == 6
    assert len(page1.positions) == 2
    assert len(page2.positions) == 2
    assert page1.positions[0].entry_time > page2.positions[0].entry_time  # newest-first


def test_get_filter_options_lists_accounts_and_instruments(migrated_db):
    _seed(
        migrated_db,
        [
            _ex("a", "Sim101", "MNQ", 100),
            _ex("b", "Sim101", "ES", 200),
            _ex("c", "Apex-1", "MNQ", 300),
        ],
    )
    opts = get_filter_options(migrated_db)
    assert set(opts["accounts"]) == {"Sim101", "Apex-1"}
    assert set(opts["instruments"]) == {"MNQ", "ES"}


def test_get_filter_options_empty_db_returns_empty_lists(migrated_db):
    opts = get_filter_options(migrated_db)
    assert opts == {"accounts": [], "instruments": []}


def test_attach_metadata_collects_notes_and_flags(migrated_db):
    _seed(
        migrated_db,
        [
            _ex("a", "Sim101", "MNQ", 100, "Buy", "Buy", "Entry", "1 L"),
            _ex("b", "Sim101", "MNQ", 200, "Sell", "Sell", "Exit", "-"),
        ],
    )
    upsert_note(migrated_db, execution_id="a", note="entry thoughts", now=150)
    set_reviewed(migrated_db, execution_id="a", reviewed=True, now=151)
    from models.execution import Execution as _E
    from services.positions import build_positions

    conn = connect(migrated_db)
    try:
        rows = conn.execute("SELECT * FROM executions").fetchall()
    finally:
        conn.close()
    execs = [
        _E(
            nt_execution_id=r["nt_execution_id"],
            account=r["account"],
            instrument=r["instrument"],
            timestamp=r["timestamp"],
            side=r["side"],
            original_action=r["original_action"],
            quantity=r["quantity"],
            price=r["price"],
            commission=r["commission"],
            entry_exit=r["entry_exit"],
            position_after=r["position_after"],
            source_order_id=r["source_order_id"],
            source_filename=r["source_filename"],
            imported_at=r["imported_at"],
        )
        for r in rows
    ]
    positions, _ = build_positions(execs)
    detail = attach_metadata(migrated_db, positions[0])
    assert detail["notes"] == {"a": "entry thoughts"}
    assert detail["reviewed"] == {"a": True}
    assert detail["custom_fields"] == {}
    assert detail["position"]["entry_execution_id"] == "a"
