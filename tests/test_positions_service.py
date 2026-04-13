from pathlib import Path

from db import connect
from models.execution import Execution
from services.import_db import bulk_insert_executions
from services.positions_service import get_position, list_positions


def _ex(
    eid,
    side,
    qty,
    ts,
    *,
    account="Sim101",
    instrument="MNQ",
    position_after="1 L",
    entry_exit="Entry",
    price=4000.0,
):
    return Execution(
        nt_execution_id=eid,
        account=account,
        instrument=instrument,
        timestamp=ts,
        side=side,
        original_action=side,
        quantity=qty,
        price=price,
        commission=0.0,
        entry_exit=entry_exit,
        position_after=position_after,
        source_order_id=None,
        source_filename="f.csv",
        imported_at=ts,
    )


def _seed(db_path: Path, rows):
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, rows)
    finally:
        conn.close()


def test_list_positions_returns_computed_positions(migrated_db: Path):
    _seed(
        migrated_db,
        [
            _ex("a", "Buy", 1, 100, position_after="1 L"),
            _ex("b", "Sell", 1, 200, entry_exit="Exit", position_after="-"),
        ],
    )
    positions = list_positions(migrated_db)
    assert len(positions) == 1
    assert positions[0].entry_execution_id == "a"


def test_list_positions_filters_by_account(migrated_db: Path):
    _seed(
        migrated_db,
        [
            _ex("a", "Buy", 1, 100, account="Sim101", position_after="1 L"),
            _ex("b", "Sell", 1, 200, account="Sim101", entry_exit="Exit", position_after="-"),
            _ex("c", "Buy", 1, 300, account="APEX-1", position_after="1 L"),
            _ex("d", "Sell", 1, 400, account="APEX-1", entry_exit="Exit", position_after="-"),
        ],
    )
    sim = list_positions(migrated_db, account="Sim101")
    apex = list_positions(migrated_db, account="APEX-1")
    assert len(sim) == 1
    assert len(apex) == 1
    assert sim[0].account == "Sim101"
    assert apex[0].account == "APEX-1"


def test_list_positions_filters_by_instrument(migrated_db: Path):
    _seed(
        migrated_db,
        [
            _ex("a", "Buy", 1, 100, instrument="MNQ", position_after="1 L"),
            _ex("b", "Sell", 1, 200, instrument="MNQ", entry_exit="Exit", position_after="-"),
            _ex("c", "Buy", 1, 300, instrument="ES", position_after="1 L"),
            _ex("d", "Sell", 1, 400, instrument="ES", entry_exit="Exit", position_after="-"),
        ],
    )
    mnq = list_positions(migrated_db, instrument="MNQ")
    es = list_positions(migrated_db, instrument="ES")
    assert len(mnq) == 1 and mnq[0].instrument == "MNQ"
    assert len(es) == 1 and es[0].instrument == "ES"


def test_get_position_by_natural_key(migrated_db: Path):
    _seed(
        migrated_db,
        [
            _ex("a", "Buy", 1, 100, position_after="1 L"),
            _ex("b", "Sell", 1, 200, entry_exit="Exit", position_after="-"),
        ],
    )
    p = get_position(migrated_db, account="Sim101", instrument="MNQ", entry_execution_id="a")
    assert p is not None
    assert p.entry_execution_id == "a"


def test_get_position_returns_none_when_missing(migrated_db: Path):
    assert (
        get_position(
            migrated_db,
            account="Sim101",
            instrument="MNQ",
            entry_execution_id="nope",
        )
        is None
    )
