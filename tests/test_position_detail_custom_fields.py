import tempfile
from pathlib import Path

from db import connect
from migrations import run_migrations
from services.custom_fields import CustomFieldsService
from services.positions_service import attach_metadata


def _fresh_db() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = connect(Path(tmp.name))
    run_migrations(conn, Path("migrations"))
    conn.close()
    return Path(tmp.name)


def _seed_execution(db_path: Path, eid: str):
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit, position_after,"
            " source_order_id, source_filename, imported_at) VALUES "
            "(?, 'Sim', 'MES', 1700000000, 'Buy', 'Buy', 1, 4500.0, 2.50, 'Entry', 1, 'O', 'f.csv', 1700000000)",
            (eid,),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


class _FakePosition:
    def __init__(self, entry: str, executions: list[str]):
        self.entry_execution_id = entry
        self.execution_ids = executions

    def model_dump(self):
        return {"entry_execution_id": self.entry_execution_id}


def test_attach_metadata_custom_fields_populated():
    db = _fresh_db()
    _seed_execution(db, "E1")
    _seed_execution(db, "E2")
    svc = CustomFieldsService(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    svc.set_execution_value("E2", d.field_id, "B-")

    result = attach_metadata(db, _FakePosition("E1", ["E1", "E2"]))
    cf = result["custom_fields"]
    assert cf["entry"] == {d.field_id: "A+"}
    assert cf["per_execution"] == [
        {"execution_id": "E2", "values": {d.field_id: "B-"}},
    ]
    assert [x["name"] for x in cf["definitions"]] == ["setup"]


def test_attach_metadata_no_custom_fields():
    db = _fresh_db()
    _seed_execution(db, "E1")
    result = attach_metadata(db, _FakePosition("E1", ["E1"]))
    cf = result["custom_fields"]
    assert cf["entry"] == {}
    assert cf["per_execution"] == []
    assert cf["definitions"] == []
