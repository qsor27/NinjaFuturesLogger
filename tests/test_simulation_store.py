import json

import pytest
from pydantic import ValidationError

from db import transaction
from models.simulation import SimulationDefinitionInput, SimulationRule
from services.simulation_store import (
    DuplicateNameError,
    create_definition,
    delete_definition,
    get_definition,
    list_definitions,
    update_definition,
)


def _inp(name="Plan A", **rule_over):
    base = dict(
        metric="losses", scope="session", comparator=">=", threshold=2, action="stop_session"
    )
    base.update(rule_over)
    return SimulationDefinitionInput(name=name, rules=[SimulationRule(**base)])


def test_round_trip(migrated_db):
    created = create_definition(migrated_db, _inp(), now=100)
    assert created.simulation_id >= 1
    assert created.created_at == created.updated_at == 100
    got = get_definition(migrated_db, created.simulation_id)
    assert got == created
    assert got.rules[0].label == "losses in session >= 2 -> stop for session"
    assert [d.name for d in list_definitions(migrated_db)] == ["Plan A"]


def test_list_orders_by_name(migrated_db):
    create_definition(migrated_db, _inp("b plan"), now=1)
    create_definition(migrated_db, _inp("A plan"), now=2)
    assert [d.name for d in list_definitions(migrated_db)] == ["A plan", "b plan"]


def test_duplicate_name_rejected(migrated_db):
    create_definition(migrated_db, _inp(), now=1)
    with pytest.raises(DuplicateNameError):
        create_definition(migrated_db, _inp(), now=2)


def test_update_bumps_updated_at_and_replaces_rules(migrated_db):
    created = create_definition(migrated_db, _inp(), now=1)
    updated = update_definition(
        migrated_db, created.simulation_id, _inp("Plan B", threshold=3), now=50
    )
    assert updated.name == "Plan B"
    assert updated.rules[0].threshold == 3
    assert updated.created_at == 1 and updated.updated_at == 50
    assert update_definition(migrated_db, 999, _inp("zzz"), now=60) is None


def test_update_to_existing_name_conflicts(migrated_db):
    create_definition(migrated_db, _inp("one"), now=1)
    two = create_definition(migrated_db, _inp("two"), now=1)
    with pytest.raises(DuplicateNameError):
        update_definition(migrated_db, two.simulation_id, _inp("one"), now=2)


def test_delete(migrated_db):
    created = create_definition(migrated_db, _inp(), now=1)
    assert delete_definition(migrated_db, created.simulation_id) is True
    assert delete_definition(migrated_db, created.simulation_id) is False
    assert get_definition(migrated_db, created.simulation_id) is None


def test_corrupt_rules_json_raises_on_read(migrated_db):
    created = create_definition(migrated_db, _inp(), now=1)
    with transaction(migrated_db) as conn:
        conn.execute(
            "UPDATE simulations SET rules_json = ? WHERE simulation_id = ?",
            (json.dumps([{"metric": "bogus"}]), created.simulation_id),
        )
    with pytest.raises(ValidationError):
        get_definition(migrated_db, created.simulation_id)
