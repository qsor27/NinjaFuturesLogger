import time

from flask import Blueprint, current_app, jsonify, request

from logging_config import get_logger
from models.browsing import LinkMember
from services.links import (
    add_members,
    create_group,
    delete_group,
    get_group,
    list_groups,
    remove_member,
    rename_group,
)

log = get_logger("http.links")


def _parse_members(raw) -> list[LinkMember]:
    if not isinstance(raw, list):
        raise ValueError("members must be a list")
    parsed: list[LinkMember] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"member {i} must be an object")
        account = item.get("account")
        instrument = item.get("instrument")
        eid = item.get("entry_execution_id")
        if not (isinstance(account, str) and isinstance(instrument, str) and isinstance(eid, str)):
            raise ValueError(f"member {i} must have string account, instrument, entry_execution_id")
        parsed.append(
            LinkMember(
                account=account,
                instrument=instrument,
                entry_execution_id=eid,
                ordinal=i,  # server will renumber on insert
            )
        )
    return parsed


def build_links_blueprint() -> Blueprint:
    bp = Blueprint("links", __name__)

    def _db_path():
        return current_app.config["FTL_DB_PATH"]

    @bp.post("/api/links")
    def create():
        body = request.get_json(silent=True) or {}
        if "members" not in body:
            return jsonify({"error": "members is required"}), 400
        try:
            members = _parse_members(body["members"])
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        label = body.get("label")
        if label is not None and not isinstance(label, str):
            return jsonify({"error": "label must be a string or null"}), 400
        try:
            gid = create_group(
                _db_path(),
                label=label,
                members=members,
                now=int(time.time()),
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"link_group_id": gid}), 201

    @bp.get("/api/links")
    def list_all():
        groups = list_groups(_db_path())
        return jsonify({"groups": [g.model_dump() for g in groups]})

    @bp.get("/api/links/<int:link_group_id>")
    def get_one(link_group_id: int):
        detail = get_group(_db_path(), link_group_id)
        if detail is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(detail.model_dump())

    @bp.patch("/api/links/<int:link_group_id>")
    def update(link_group_id: int):
        if get_group(_db_path(), link_group_id) is None:
            return jsonify({"error": "not found"}), 404
        body = request.get_json(silent=True) or {}
        if "label" in body:
            label = body["label"]
            if label is not None and not isinstance(label, str):
                return jsonify({"error": "label must be a string or null"}), 400
            rename_group(_db_path(), link_group_id=link_group_id, label=label)
        if "add_members" in body:
            try:
                to_add = _parse_members(body["add_members"])
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            try:
                add_members(_db_path(), link_group_id=link_group_id, members=to_add)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
        if "remove_members" in body:
            try:
                to_remove = _parse_members(body["remove_members"])
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            for m in to_remove:
                remove_member(
                    _db_path(),
                    link_group_id=link_group_id,
                    account=m.account,
                    instrument=m.instrument,
                    entry_execution_id=m.entry_execution_id,
                )
        return jsonify({"ok": True})

    @bp.delete("/api/links/<int:link_group_id>")
    def delete(link_group_id: int):
        if get_group(_db_path(), link_group_id) is None:
            return jsonify({"error": "not found"}), 404
        delete_group(_db_path(), link_group_id)
        return jsonify({"ok": True})

    return bp
