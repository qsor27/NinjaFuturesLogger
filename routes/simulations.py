"""Simulation Analysis API. Thin: parse, call service/store, serialize."""

from __future__ import annotations

import time
from datetime import date

from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError

from models.simulation import (
    SimulationDefinitionInput,
    SimulationRule,
    SimulationRunRequest,
    vocabulary,
)
from models.statistics import StatsFilter
from routes import db_path as _db_path
from routes.stats import _parse_filter
from services.simulation_service import SimulationService
from services.simulation_store import (
    DuplicateNameError,
    create_definition,
    delete_definition,
    get_definition,
    list_definitions,
    update_definition,
)


def _validation_response(e: ValidationError):
    details = [{"loc": [str(x) for x in err["loc"]], "msg": err["msg"]} for err in e.errors()]
    first = details[0] if details else {"loc": [], "msg": "invalid input"}
    message = f"{'.'.join(first['loc'])}: {first['msg']}" if first["loc"] else first["msg"]
    return jsonify({"error": message, "details": details}), 400


def _parse_date(v) -> date | None:
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise ValueError("dates must be ISO YYYY-MM-DD strings")
    try:
        return date.fromisoformat(v)
    except ValueError as e:
        raise ValueError("dates must be ISO YYYY-MM-DD") from e


def _json_object():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None
    return body


def build_simulations_blueprint() -> Blueprint:
    bp = Blueprint("simulations", __name__)

    def _service() -> SimulationService:
        return SimulationService(current_app.config["FTL_CONFIG"])

    @bp.get("/api/simulations/vocabulary")
    def get_vocabulary():
        return jsonify(vocabulary())

    @bp.get("/api/simulations")
    def list_all():
        return jsonify(
            {"simulations": [d.model_dump(mode="json") for d in list_definitions(_db_path())]}
        )

    @bp.post("/api/simulations")
    def create():
        body = _json_object()
        if body is None:
            return jsonify({"error": "body must be a JSON object"}), 400
        try:
            inp = SimulationDefinitionInput.model_validate(body)
        except ValidationError as e:
            return _validation_response(e)
        try:
            created = create_definition(_db_path(), inp, now=int(time.time()))
        except DuplicateNameError as e:
            return jsonify({"error": str(e)}), 409
        return jsonify(created.model_dump(mode="json")), 201

    @bp.get("/api/simulations/<int:simulation_id>")
    def get_one(simulation_id: int):
        d = get_definition(_db_path(), simulation_id)
        if d is None:
            return jsonify({"error": "simulation not found"}), 404
        return jsonify(d.model_dump(mode="json"))

    @bp.put("/api/simulations/<int:simulation_id>")
    def update(simulation_id: int):
        body = _json_object()
        if body is None:
            return jsonify({"error": "body must be a JSON object"}), 400
        try:
            inp = SimulationDefinitionInput.model_validate(body)
        except ValidationError as e:
            return _validation_response(e)
        try:
            updated = update_definition(_db_path(), simulation_id, inp, now=int(time.time()))
        except DuplicateNameError as e:
            return jsonify({"error": str(e)}), 409
        if updated is None:
            return jsonify({"error": "simulation not found"}), 404
        return jsonify(updated.model_dump(mode="json"))

    @bp.delete("/api/simulations/<int:simulation_id>")
    def delete(simulation_id: int):
        if not delete_definition(_db_path(), simulation_id):
            return jsonify({"error": "simulation not found"}), 404
        return "", 204

    @bp.post("/api/simulations/run")
    def run_unsaved():
        body = _json_object()
        if body is None:
            return jsonify({"error": "body must be a JSON object"}), 400
        try:
            accounts = body.get("accounts") or []
            if not isinstance(accounts, list):
                raise ValueError("accounts must be a list")
            side = body.get("side") or None
            if side not in (None, "Long", "Short"):
                raise ValueError("side must be 'Long' or 'Short'")
            req = SimulationRunRequest(
                rules=body.get("rules"),
                accounts=tuple(accounts),
                from_date=_parse_date(body.get("from")),
                to_date=_parse_date(body.get("to")),
                side=side,
            )
        except ValidationError as e:
            return _validation_response(e)
        except (ValueError, TypeError) as e:
            return jsonify({"error": str(e), "details": []}), 400
        filter_ = StatsFilter(
            accounts=req.accounts, from_date=req.from_date, to_date=req.to_date, side=req.side
        )
        return jsonify(_service().run(req.rules, filter_).model_dump(mode="json"))

    @bp.get("/api/simulations/<int:simulation_id>/run")
    def run_saved(simulation_id: int):
        d = get_definition(_db_path(), simulation_id)
        if d is None:
            return jsonify({"error": "simulation not found"}), 404
        try:
            filter_ = _parse_filter(request.args)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        rules: list[SimulationRule] = d.rules
        return jsonify(_service().run(rules, filter_).model_dump(mode="json"))

    return bp
