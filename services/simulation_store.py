"""Persistence for saved simulation definitions (rule sets).

rules_json is validated through SimulationRule on write and on read so a
corrupt row fails loudly instead of silently degrading.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from db import read_conn, transaction
from models.simulation import SimulationDefinition, SimulationDefinitionInput, SimulationRule


class DuplicateNameError(ValueError):
    """A simulation name collided with the UNIQUE constraint."""


def _dump_rules(rules: list[SimulationRule]) -> str:
    return json.dumps([r.model_dump() for r in rules])


def _row_to_definition(row: sqlite3.Row) -> SimulationDefinition:
    rules = [SimulationRule(**r) for r in json.loads(row["rules_json"])]
    return SimulationDefinition(
        simulation_id=int(row["simulation_id"]),
        name=row["name"],
        rules=rules,
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
    )


_COLS = "simulation_id, name, rules_json, created_at, updated_at"


def list_definitions(db_path: Path | str) -> list[SimulationDefinition]:
    with read_conn(db_path) as conn:
        rows = conn.execute(
            f"SELECT {_COLS} FROM simulations ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [_row_to_definition(r) for r in rows]


def get_definition(db_path: Path | str, simulation_id: int) -> SimulationDefinition | None:
    with read_conn(db_path) as conn:
        row = conn.execute(
            f"SELECT {_COLS} FROM simulations WHERE simulation_id = ?", (simulation_id,)
        ).fetchone()
    return None if row is None else _row_to_definition(row)


def create_definition(
    db_path: Path | str, inp: SimulationDefinitionInput, *, now: int
) -> SimulationDefinition:
    try:
        with transaction(db_path) as conn:
            cur = conn.execute(
                "INSERT INTO simulations (name, rules_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (inp.name, _dump_rules(inp.rules), now, now),
            )
            new_id = int(cur.lastrowid)
    except sqlite3.IntegrityError as e:
        raise DuplicateNameError(f"a simulation named {inp.name!r} already exists") from e
    return SimulationDefinition(
        simulation_id=new_id, name=inp.name, rules=inp.rules, created_at=now, updated_at=now
    )


def update_definition(
    db_path: Path | str, simulation_id: int, inp: SimulationDefinitionInput, *, now: int
) -> SimulationDefinition | None:
    try:
        with transaction(db_path) as conn:
            row = conn.execute(
                "SELECT created_at FROM simulations WHERE simulation_id = ?", (simulation_id,)
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE simulations SET name = ?, rules_json = ?, updated_at = ? "
                "WHERE simulation_id = ?",
                (inp.name, _dump_rules(inp.rules), now, simulation_id),
            )
            created_at = int(row["created_at"])
    except sqlite3.IntegrityError as e:
        raise DuplicateNameError(f"a simulation named {inp.name!r} already exists") from e
    return SimulationDefinition(
        simulation_id=simulation_id,
        name=inp.name,
        rules=inp.rules,
        created_at=created_at,
        updated_at=now,
    )


def delete_definition(db_path: Path | str, simulation_id: int) -> bool:
    with transaction(db_path) as conn:
        cur = conn.execute("DELETE FROM simulations WHERE simulation_id = ?", (simulation_id,))
        return cur.rowcount > 0
