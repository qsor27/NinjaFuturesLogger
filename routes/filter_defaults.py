from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError

from config import (
    PositionsFilterDefault,
    StatsFilterDefault,
    load_config,
    save_filter_default,
)

_VALID_SCOPES = ("positions", "stats")


def build_filter_defaults_blueprint() -> Blueprint:
    bp = Blueprint("filter_defaults", __name__)

    def _cfg_path() -> str:
        return current_app.config["FTL_CONFIG_PATH"]

    def _reload() -> None:
        """Refresh the in-memory Config after a save."""
        current_app.config["FTL_CONFIG"] = load_config(_cfg_path())

    @bp.get("/api/filter-defaults")
    def get_all():
        cfg = current_app.config["FTL_CONFIG"]
        fd = cfg.filter_defaults
        return jsonify(
            {
                "positions": (fd.positions.model_dump() if fd.positions else None),
                "stats": (fd.stats.model_dump() if fd.stats else None),
            }
        )

    @bp.put("/api/filter-defaults/<scope>")
    def put_scope(scope: str):
        if scope not in _VALID_SCOPES:
            return jsonify({"error": f"invalid scope: {scope!r}"}), 400

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "body must be a JSON object"}), 400

        model_cls = (
            PositionsFilterDefault if scope == "positions" else StatsFilterDefault
        )
        try:
            model_cls(**body)
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400

        try:
            save_filter_default(_cfg_path(), scope, body)
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400
        _reload()
        return jsonify({"ok": True})

    @bp.delete("/api/filter-defaults/<scope>")
    def delete_scope(scope: str):
        if scope not in _VALID_SCOPES:
            return jsonify({"error": f"invalid scope: {scope!r}"}), 400
        save_filter_default(_cfg_path(), scope, None)
        _reload()
        return jsonify({"ok": True})

    return bp
