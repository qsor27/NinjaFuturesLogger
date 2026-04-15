import tempfile
from pathlib import Path

import pytest

from db import connect
from migrations import run_migrations
from services.custom_fields import CustomFieldsService


def _fresh_db() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = connect(Path(tmp.name))
    run_migrations(conn, Path("migrations"))
    conn.close()
    return Path(tmp.name)


def _seed_execution(db_path: Path, eid: str = "E1") -> None:
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


def test_create_and_list_definitions():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    svc.create_definition(name="setup", field_type="dropdown")
    svc.create_definition(name="confidence", field_type="number", display_order=1)
    defs = svc.list_definitions(include_inactive=True)
    assert [d.name for d in defs] == ["setup", "confidence"]
    assert defs[0].field_type == "dropdown"


def test_create_definition_rejects_duplicate_name():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    svc.create_definition(name="setup", field_type="text")
    with pytest.raises(ValueError):
        svc.create_definition(name="setup", field_type="text")


def test_create_definition_rejects_bad_field_type():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    with pytest.raises(ValueError):
        svc.create_definition(name="x", field_type="bogus")


def test_update_definition_renames():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.update_definition(d.field_id, name="Setup Type")
    defs = svc.list_definitions(include_inactive=True)
    assert defs[0].name == "Setup Type"


def test_update_definition_changes_is_active():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.update_definition(d.field_id, is_active=False)
    defs = svc.list_definitions(include_inactive=False)
    assert defs == []
    defs = svc.list_definitions(include_inactive=True)
    assert defs[0].is_active is False


def test_update_definition_rejects_type_change_with_values():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    with pytest.raises(ValueError):
        svc.update_definition(d.field_id, field_type="number")


def test_delete_definition_two_step():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    count = svc.affected_executions(d.field_id)
    assert count == 1
    with pytest.raises(ValueError):
        svc.delete_definition(d.field_id, confirm_count=0)
    svc.delete_definition(d.field_id, confirm_count=1)
    assert svc.list_definitions(include_inactive=True) == []


def test_delete_definition_cascades_values():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    svc.delete_definition(d.field_id, confirm_count=1)
    values = svc.get_execution_values("E1")
    assert values == {}


def test_replace_options_preserves_option_id_for_unchanged_values():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    d = svc.create_definition(name="setup", field_type="dropdown")
    svc.replace_options(
        d.field_id,
        [
            {"value": "Breakout", "display_order": 0},
            {"value": "Reversal", "display_order": 1},
        ],
    )
    first = svc.list_options(d.field_id)
    first_ids = {o.value: o.option_id for o in first}

    svc.replace_options(
        d.field_id,
        [
            {"value": "Reversal", "display_order": 0},
            {"value": "Breakout", "display_order": 1},
            {"value": "Trend", "display_order": 2},
        ],
    )
    second = svc.list_options(d.field_id)
    second_ids = {o.value: o.option_id for o in second}

    assert second_ids["Breakout"] == first_ids["Breakout"]
    assert second_ids["Reversal"] == first_ids["Reversal"]
    assert "Trend" in second_ids
    assert [o.value for o in second] == ["Reversal", "Breakout", "Trend"]


def test_replace_options_deletes_removed_values():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    d = svc.create_definition(name="setup", field_type="dropdown")
    svc.replace_options(
        d.field_id,
        [
            {"value": "A", "display_order": 0},
            {"value": "B", "display_order": 1},
        ],
    )
    svc.replace_options(d.field_id, [{"value": "A", "display_order": 0}])
    options = svc.list_options(d.field_id)
    assert [o.value for o in options] == ["A"]


def test_set_execution_value_text():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+ setup")
    values = svc.get_execution_values("E1")
    assert values == {d.field_id: "A+ setup"}


def test_set_execution_value_number_stores_as_json():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="confidence", field_type="number")
    svc.set_execution_value("E1", d.field_id, 4.0)
    values = svc.get_execution_values("E1")
    assert values == {d.field_id: 4.0}


def test_set_execution_value_number_rejects_non_numeric():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="c", field_type="number")
    with pytest.raises(ValueError):
        svc.set_execution_value("E1", d.field_id, "not a number")


def test_set_execution_value_date_iso_format():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="plan_date", field_type="date")
    svc.set_execution_value("E1", d.field_id, "2026-04-13")
    values = svc.get_execution_values("E1")
    assert values == {d.field_id: "2026-04-13"}


def test_set_execution_value_date_rejects_bad_format():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="plan_date", field_type="date")
    with pytest.raises(ValueError):
        svc.set_execution_value("E1", d.field_id, "04/13/2026")


def test_set_execution_value_boolean():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="in_plan", field_type="boolean")
    svc.set_execution_value("E1", d.field_id, True)
    values = svc.get_execution_values("E1")
    assert values == {d.field_id: True}


def test_set_execution_value_dropdown_validates_against_options():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="dropdown")
    svc.replace_options(
        d.field_id,
        [
            {"value": "Breakout", "display_order": 0},
        ],
    )
    svc.set_execution_value("E1", d.field_id, "Breakout")
    with pytest.raises(ValueError):
        svc.set_execution_value("E1", d.field_id, "NotAnOption")


def test_set_execution_value_strips_split_suffix():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db, "E1")
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1#close", d.field_id, "A+")
    values = svc.get_execution_values("E1")
    assert values == {d.field_id: "A+"}
    values2 = svc.get_execution_values("E1#open")
    assert values2 == {d.field_id: "A+"}


def test_set_execution_value_empty_deletes_row():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    svc.set_execution_value("E1", d.field_id, "")
    values = svc.get_execution_values("E1")
    assert values == {}


def test_values_for_position_splits_entry_and_per_execution():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db, "E1")
    _seed_execution(db, "E2")
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    svc.set_execution_value("E2", d.field_id, "B-")

    result = svc.values_for_position(
        execution_ids=["E1", "E2"],
        entry_execution_id="E1",
    )
    assert result["entry"] == {d.field_id: "A+"}
    assert result["per_execution"] == [
        {"execution_id": "E2", "values": {d.field_id: "B-"}},
    ]
    assert [d_["name"] for d_ in result["definitions"]] == ["setup"]


def test_values_for_position_inactive_field_appears_in_values_not_definitions():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db, "E1")
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    svc.update_definition(d.field_id, is_active=False)

    result = svc.values_for_position(
        execution_ids=["E1"],
        entry_execution_id="E1",
    )
    assert result["entry"] == {d.field_id: "A+"}
    assert result["definitions"] == []
