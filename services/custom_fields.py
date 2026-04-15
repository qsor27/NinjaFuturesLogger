"""CustomFieldsService — owns all CRUD for custom field definitions,
options, and execution values.

Rules enforced here:
- Every mutator on execution values calls notes.strip_split_suffix so
  synthesized #close/#open sub-fill IDs inherit the parent row's values.
- Value encoding per field_type is defined in one place (_encode/_decode).
- Dropdown writes are validated against the field's current options.
- Two-step delete flow: affected_executions() returns the count; the UI
  passes it back as confirm_count to delete_definition().
"""

import json
import time
from pathlib import Path
from typing import Any

from db import connect
from models.settings import (
    CustomFieldDefinition,
    CustomFieldOption,
    CustomFieldOptionInput,
)
from services.notes import strip_split_suffix

_FIELD_TYPES = ("text", "number", "dropdown", "date", "boolean")


def _now() -> int:
    return int(time.time())


class CustomFieldsService:
    def __init__(self, db_path: Path | str):
        self._db_path = db_path

    # ---- definitions ----

    def list_definitions(self, include_inactive: bool = True) -> list[CustomFieldDefinition]:
        conn = connect(self._db_path)
        try:
            sql = (
                "SELECT field_id, name, field_type, is_active, display_order, created_at "
                "FROM custom_fields "
            )
            if not include_inactive:
                sql += "WHERE is_active = 1 "
            sql += "ORDER BY display_order, field_id"
            rows = conn.execute(sql).fetchall()
        finally:
            conn.close()
        return [
            CustomFieldDefinition(
                field_id=r["field_id"],
                name=r["name"],
                field_type=r["field_type"],
                is_active=bool(r["is_active"]),
                display_order=r["display_order"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def get_definition(self, field_id: int) -> CustomFieldDefinition | None:
        conn = connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT field_id, name, field_type, is_active, display_order, created_at "
                "FROM custom_fields WHERE field_id = ?",
                (field_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return CustomFieldDefinition(
            field_id=row["field_id"],
            name=row["name"],
            field_type=row["field_type"],
            is_active=bool(row["is_active"]),
            display_order=row["display_order"],
            created_at=row["created_at"],
        )

    def create_definition(
        self,
        *,
        name: str,
        field_type: str,
        display_order: int = 0,
    ) -> CustomFieldDefinition:
        if field_type not in _FIELD_TYPES:
            raise ValueError(f"invalid field_type: {field_type!r}")
        if not name:
            raise ValueError("name is required")
        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN")
            try:
                cur = conn.execute(
                    "INSERT INTO custom_fields (name, field_type, is_active, "
                    "display_order, created_at) VALUES (?, ?, 1, ?, ?)",
                    (name, field_type, display_order, _now()),
                )
            except Exception as e:
                conn.execute("ROLLBACK")
                raise ValueError(f"duplicate name: {name!r}") from e
            field_id = cur.lastrowid
            conn.execute("COMMIT")
        finally:
            conn.close()
        return self.get_definition(field_id)  # type: ignore[return-value]

    def update_definition(
        self,
        field_id: int,
        *,
        name: str | None = None,
        field_type: str | None = None,
        is_active: bool | None = None,
        display_order: int | None = None,
    ) -> CustomFieldDefinition:
        existing = self.get_definition(field_id)
        if existing is None:
            raise ValueError(f"no such field_id: {field_id}")
        if field_type is not None and field_type != existing.field_type:
            count = self.affected_executions(field_id)
            if count > 0:
                raise ValueError(f"cannot change field_type while {count} executions have values")
            if field_type not in _FIELD_TYPES:
                raise ValueError(f"invalid field_type: {field_type!r}")
        updates: list[tuple[str, Any]] = []
        if name is not None:
            updates.append(("name = ?", name))
        if field_type is not None:
            updates.append(("field_type = ?", field_type))
        if is_active is not None:
            updates.append(("is_active = ?", int(bool(is_active))))
        if display_order is not None:
            updates.append(("display_order = ?", display_order))
        if not updates:
            return existing
        set_clause = ", ".join(u[0] for u in updates)
        params = [u[1] for u in updates] + [field_id]
        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    f"UPDATE custom_fields SET {set_clause} WHERE field_id = ?",
                    tuple(params),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return self.get_definition(field_id)  # type: ignore[return-value]

    def affected_executions(self, field_id: int) -> int:
        conn = connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM execution_custom_field_values WHERE field_id = ?",
                (field_id,),
            ).fetchone()
        finally:
            conn.close()
        return int(row[0])

    def delete_definition(self, field_id: int, *, confirm_count: int) -> None:
        actual = self.affected_executions(field_id)
        if confirm_count != actual:
            raise ValueError(f"confirm_count {confirm_count} does not match actual {actual}")
        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN")
            try:
                conn.execute("DELETE FROM custom_fields WHERE field_id = ?", (field_id,))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    # ---- options ----

    def list_options(self, field_id: int) -> list[CustomFieldOption]:
        conn = connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT option_id, field_id, value, display_order "
                "FROM custom_field_options WHERE field_id = ? "
                "ORDER BY display_order, option_id",
                (field_id,),
            ).fetchall()
        finally:
            conn.close()
        return [
            CustomFieldOption(
                option_id=r["option_id"],
                field_id=r["field_id"],
                value=r["value"],
                display_order=r["display_order"],
            )
            for r in rows
        ]

    def replace_options(
        self,
        field_id: int,
        options: list[dict],
    ) -> list[CustomFieldOption]:
        """Replace-in-place. Unchanged `value`s keep their option_id."""
        validated = [CustomFieldOptionInput(**o) for o in options]
        existing = {o.value: o for o in self.list_options(field_id)}
        new_values = {o.value for o in validated}
        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN")
            try:
                for value, opt in existing.items():
                    if value not in new_values:
                        conn.execute(
                            "DELETE FROM custom_field_options WHERE option_id = ?",
                            (opt.option_id,),
                        )
                for v in validated:
                    if v.value in existing:
                        conn.execute(
                            "UPDATE custom_field_options SET display_order = ? "
                            "WHERE option_id = ?",
                            (v.display_order, existing[v.value].option_id),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO custom_field_options "
                            "(field_id, value, display_order) VALUES (?, ?, ?)",
                            (field_id, v.value, v.display_order),
                        )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return self.list_options(field_id)

    # ---- execution values ----

    def _encode(self, field_type: str, value: Any, options: list[str] | None) -> str:
        if field_type == "text":
            if not isinstance(value, str):
                raise ValueError("text value must be a string")
            return value
        if field_type == "number":
            try:
                return json.dumps(float(value))
            except (TypeError, ValueError) as e:
                raise ValueError(f"number value must be numeric: {value!r}") from e
        if field_type == "date":
            if not isinstance(value, str):
                raise ValueError("date value must be an ISO string")
            try:
                from datetime import date as _date

                _date.fromisoformat(value)
            except ValueError as e:
                raise ValueError(f"date must be YYYY-MM-DD: {value!r}") from e
            return value
        if field_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError("boolean value must be a Python bool")
            return "true" if value else "false"
        if field_type == "dropdown":
            if not isinstance(value, str):
                raise ValueError("dropdown value must be a string")
            if options is not None and value not in options:
                raise ValueError(f"not an option for this field: {value!r}")
            return value
        raise ValueError(f"unknown field_type: {field_type!r}")

    def _decode(self, field_type: str, raw: str) -> Any:
        if field_type == "text":
            return raw
        if field_type == "number":
            return float(json.loads(raw))
        if field_type == "date":
            return raw
        if field_type == "boolean":
            return raw == "true"
        if field_type == "dropdown":
            return raw
        return raw

    def get_execution_values(self, execution_id: str) -> dict[int, Any]:
        real_id = strip_split_suffix(execution_id)
        conn = connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT v.field_id, v.value, f.field_type "
                "FROM execution_custom_field_values v "
                "JOIN custom_fields f ON f.field_id = v.field_id "
                "WHERE v.execution_id = ?",
                (real_id,),
            ).fetchall()
        finally:
            conn.close()
        return {r["field_id"]: self._decode(r["field_type"], r["value"]) for r in rows}

    def set_execution_value(
        self,
        execution_id: str,
        field_id: int,
        value: Any,
    ) -> None:
        real_id = strip_split_suffix(execution_id)
        defn = self.get_definition(field_id)
        if defn is None:
            raise ValueError(f"no such field_id: {field_id}")
        if value is None or value == "":
            conn = connect(self._db_path)
            try:
                conn.execute("BEGIN")
                try:
                    conn.execute(
                        "DELETE FROM execution_custom_field_values "
                        "WHERE execution_id = ? AND field_id = ?",
                        (real_id, field_id),
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            finally:
                conn.close()
            return

        options: list[str] | None = None
        if defn.field_type == "dropdown":
            options = [o.value for o in self.list_options(field_id)]
        encoded = self._encode(defn.field_type, value, options)

        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    "INSERT INTO execution_custom_field_values "
                    "(execution_id, field_id, value, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(execution_id, field_id) DO UPDATE SET "
                    "value = excluded.value, updated_at = excluded.updated_at",
                    (real_id, field_id, encoded, _now()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def values_for_position(
        self,
        *,
        execution_ids: list[str],
        entry_execution_id: str,
    ) -> dict:
        """Return `{entry, per_execution, definitions}` for a position."""
        real_entry = strip_split_suffix(entry_execution_id)
        real_all = sorted({strip_split_suffix(e) for e in execution_ids})

        entry_values = self.get_execution_values(real_entry)
        per_execution: list[dict] = []
        for eid in real_all:
            if eid == real_entry:
                continue
            values = self.get_execution_values(eid)
            if values:
                per_execution.append({"execution_id": eid, "values": values})

        definitions = self.list_definitions(include_inactive=False)
        return {
            "entry": entry_values,
            "per_execution": per_execution,
            "definitions": [d.model_dump() for d in definitions],
        }
