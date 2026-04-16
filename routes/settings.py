from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, render_template, request
from pydantic import ValidationError

from config import load_config
from db import connect
from logging_config import get_logger
from models.settings import InstrumentConfig
from services.instruments import get_registry
from services.ohlc.coverage_state import (
    list_coverage,
    reactivate,
    refresh_instrument_coverage_state,
    retire_now,
    set_pinned,
)

log = get_logger("http.settings")


def build_settings_blueprint() -> Blueprint:
    bp = Blueprint("settings", __name__)

    # ---- instruments ----

    @bp.get("/api/config/instruments")
    def list_instruments():
        reg = get_registry()
        return jsonify({"instruments": {symbol: cfg.model_dump() for symbol, cfg in reg.list()}})

    @bp.put("/api/config/instruments/<symbol>")
    def put_instrument(symbol: str):
        body = request.get_json(silent=True) or {}
        try:
            cfg = InstrumentConfig(**body)
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400
        get_registry().put(symbol, cfg)
        return jsonify({"instrument": cfg.model_dump()})

    @bp.delete("/api/config/instruments/<symbol>")
    def delete_instrument(symbol: str):
        try:
            get_registry().delete(symbol)
        except KeyError:
            return jsonify({"error": "not found"}), 404
        return "", 204

    # ---- coverage state ----

    def _db_path() -> str:
        return current_app.config["FTL_DB_PATH"]

    @bp.get("/api/settings/coverage")
    def coverage_list():
        import time as _time

        conn = connect(_db_path())
        try:
            refresh_instrument_coverage_state(conn, now=int(_time.time()))
            rows = list_coverage(conn)
        finally:
            conn.close()
        return jsonify(
            {
                "rows": [
                    {
                        "instrument": r.instrument,
                        "state": r.state,
                        "last_execution_at": r.last_execution_at,
                        "pinned": r.pinned,
                        "retired_at": r.retired_at,
                    }
                    for r in rows
                ]
            }
        )

    @bp.post("/api/settings/coverage/<instrument>/pin")
    def coverage_pin(instrument: str):
        import time as _time

        data = request.get_json(silent=True) or {}
        pinned = bool(data.get("pinned", True))
        conn = connect(_db_path())
        try:
            set_pinned(conn, instrument=instrument, pinned=pinned, now=int(_time.time()))
            refresh_instrument_coverage_state(conn, now=int(_time.time()))
        finally:
            conn.close()
        return jsonify({"instrument": instrument, "pinned": pinned})

    @bp.post("/api/settings/coverage/<instrument>/retire")
    def coverage_retire(instrument: str):
        import time as _time

        conn = connect(_db_path())
        try:
            retire_now(conn, instrument=instrument, now=int(_time.time()))
        finally:
            conn.close()
        return jsonify({"instrument": instrument, "state": "retired"})

    @bp.post("/api/settings/coverage/<instrument>/reactivate")
    def coverage_reactivate(instrument: str):
        import time as _time

        conn = connect(_db_path())
        try:
            reactivate(conn, instrument=instrument, now=int(_time.time()))
            refresh_instrument_coverage_state(conn, now=int(_time.time()))
        finally:
            conn.close()
        return jsonify({"instrument": instrument, "state": "active"})

    # ---- chart defaults ----

    @bp.get("/api/config/chart-defaults")
    def get_chart_defaults():
        from services.chart_defaults import get_defaults

        d = get_defaults(current_app.config["FTL_DB_PATH"])
        cfg = current_app.config["FTL_CONFIG"]
        return jsonify(
            {
                "default_timeframe": d["default_timeframe"],
                "volume_visible_default": d["volume_visible_default"],
                "display_timezone": cfg.display_timezone,
                "source_timezone": cfg.session.source_timezone,
            }
        )

    @bp.put("/api/config/chart-defaults")
    def put_chart_defaults():
        from config import save_display_timezone, save_source_timezone
        from services.chart_defaults import save_defaults

        body = request.get_json(silent=True) or {}
        tf = body.get("default_timeframe")
        vv = body.get("volume_visible_default")
        dtz = body.get("display_timezone")
        source_tz_provided = "source_timezone" in body
        stz = body.get("source_timezone")

        if tf not in ("1m", "5m", "15m", "1h", "4h", "1d"):
            return jsonify({"error": "invalid default_timeframe"}), 400
        if not isinstance(vv, bool):
            return jsonify({"error": "volume_visible_default must be boolean"}), 400
        if dtz is not None:
            try:
                ZoneInfo(dtz)
            except Exception:
                return jsonify({"error": "invalid display_timezone"}), 400
        if source_tz_provided and stz is not None:
            try:
                ZoneInfo(stz)
            except Exception:
                return jsonify({"error": "invalid source_timezone"}), 400

        db_path = current_app.config["FTL_DB_PATH"]
        save_defaults(db_path, default_timeframe=tf, volume_visible_default=vv)

        cfg_path = current_app.config["FTL_CONFIG_PATH"]
        save_display_timezone(cfg_path, dtz)
        if source_tz_provided:
            save_source_timezone(cfg_path, stz)

        current_app.config["FTL_CONFIG"] = load_config(cfg_path)

        return jsonify(
            {
                "default_timeframe": tf,
                "volume_visible_default": vv,
                "display_timezone": dtz,
                "source_timezone": current_app.config["FTL_CONFIG"].session.source_timezone,
            }
        )

    # ---- custom field definitions ----

    def _svc():
        from services.custom_fields import CustomFieldsService

        return CustomFieldsService(current_app.config["FTL_DB_PATH"])

    @bp.get("/api/custom-fields")
    def list_custom_fields():
        defs = _svc().list_definitions(include_inactive=True)
        return jsonify({"fields": [d.model_dump() for d in defs]})

    @bp.post("/api/custom-fields")
    def create_custom_field():
        body = request.get_json(silent=True) or {}
        name = body.get("name")
        field_type = body.get("field_type")
        display_order = body.get("display_order", 0)
        if not isinstance(name, str) or not name:
            return jsonify({"error": "name is required"}), 400
        try:
            d = _svc().create_definition(
                name=name,
                field_type=field_type,
                display_order=display_order,
            )
        except ValueError as e:
            msg = str(e)
            if "duplicate" in msg:
                return jsonify({"error": msg}), 409
            return jsonify({"error": msg}), 400
        return jsonify({"field": d.model_dump()})

    @bp.put("/api/custom-fields/<int:field_id>")
    def update_custom_field(field_id: int):
        body = request.get_json(silent=True) or {}
        try:
            d = _svc().update_definition(
                field_id,
                name=body.get("name"),
                field_type=body.get("field_type"),
                is_active=body.get("is_active"),
                display_order=body.get("display_order"),
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"field": d.model_dump()})

    @bp.delete("/api/custom-fields/<int:field_id>")
    def delete_custom_field(field_id: int):
        svc = _svc()
        actual = svc.affected_executions(field_id)
        confirm_raw = request.args.get("confirm_count")
        if confirm_raw is None:
            return jsonify({"affected_executions": actual}), 409
        try:
            svc.delete_definition(field_id, confirm_count=int(confirm_raw))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return "", 204

    @bp.get("/api/custom-fields/<int:field_id>/options")
    def list_custom_field_options(field_id: int):
        opts = _svc().list_options(field_id)
        return jsonify({"options": [o.model_dump() for o in opts]})

    @bp.put("/api/custom-fields/<int:field_id>/options")
    def replace_custom_field_options(field_id: int):
        body = request.get_json(silent=True) or {}
        options = body.get("options")
        if not isinstance(options, list):
            return jsonify({"error": "options must be a list"}), 400
        try:
            result = _svc().replace_options(field_id, options)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"options": [o.model_dump() for o in result]})

    # ---- execution-level custom field values ----

    def _execution_exists(execution_id: str) -> bool:
        from db import connect
        from services.notes import strip_split_suffix

        real_id = strip_split_suffix(execution_id)
        conn = connect(current_app.config["FTL_DB_PATH"])
        try:
            row = conn.execute(
                "SELECT 1 FROM executions WHERE nt_execution_id = ?",
                (real_id,),
            ).fetchone()
        finally:
            conn.close()
        return row is not None

    @bp.get("/api/executions/<execution_id>/custom-fields")
    def get_execution_custom_fields(execution_id: str):
        if not _execution_exists(execution_id):
            return jsonify({"error": "execution not found"}), 404
        values = _svc().get_execution_values(execution_id)
        return jsonify({"values": {str(k): v for k, v in values.items()}})

    @bp.put("/api/executions/<execution_id>/custom-fields/<int:field_id>")
    def put_execution_custom_field(execution_id: str, field_id: int):
        if not _execution_exists(execution_id):
            return jsonify({"error": "execution not found"}), 404
        body = request.get_json(silent=True) or {}
        value = body.get("value")
        try:
            _svc().set_execution_value(execution_id, field_id, value)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True})

    @bp.get("/api/positions/<account>/<instrument>/<entry_execution_id>/custom-fields")
    def get_position_custom_fields(account: str, instrument: str, entry_execution_id: str):
        from services.positions_service import get_position

        p = get_position(
            current_app.config["FTL_DB_PATH"],
            account=account,
            instrument=instrument,
            entry_execution_id=entry_execution_id,
        )
        if p is None:
            return jsonify({"error": "not found"}), 404
        result = _svc().values_for_position(
            execution_ids=p.execution_ids,
            entry_execution_id=p.entry_execution_id,
        )
        result["entry"] = {str(k): v for k, v in result["entry"].items()}
        result["per_execution"] = [
            {
                "execution_id": r["execution_id"],
                "values": {str(k): v for k, v in r["values"].items()},
            }
            for r in result["per_execution"]
        ]
        return jsonify(result)

    # ---- UI pages ----

    @bp.get("/settings")
    def settings_index_page():
        return render_template("settings_index.html")

    @bp.get("/settings/instruments")
    def settings_instruments_page():
        return render_template("settings_instruments.html")

    @bp.get("/settings/chart")
    def settings_chart_page():
        return render_template("settings_chart.html")

    @bp.get("/settings/custom-fields")
    def settings_custom_fields_page():
        return render_template("settings_custom_fields.html")

    return bp
