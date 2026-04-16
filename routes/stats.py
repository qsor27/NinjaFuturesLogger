from datetime import date

from flask import Blueprint, current_app, jsonify, request

from models.statistics import StatsFilter
from services.statistics import StatisticsService


def _parse_filter(args) -> StatsFilter:
    account = args.get("account") or None

    def _parse_date(key: str) -> date | None:
        v = args.get(key)
        if v is None or v == "":
            return None
        try:
            return date.fromisoformat(v)
        except ValueError as e:
            raise ValueError(f"{key} must be ISO YYYY-MM-DD") from e

    raw_side = args.get("side") or None
    if raw_side not in (None, "Long", "Short"):
        raise ValueError("side must be 'Long' or 'Short'")

    return StatsFilter(
        account=account,
        from_date=_parse_date("from"),
        to_date=_parse_date("to"),
        side=raw_side,
    )


def build_stats_blueprint() -> Blueprint:
    bp = Blueprint("stats", __name__)

    def _service() -> StatisticsService:
        return StatisticsService(current_app.config["FTL_CONFIG"])

    def _dispatch(method_name: str):
        try:
            filter_ = _parse_filter(request.args)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        method = getattr(_service(), method_name)
        return jsonify(method(filter_).model_dump())

    @bp.get("/api/stats/summary")
    def summary():
        return _dispatch("summary")

    @bp.get("/api/stats/by-instrument")
    def by_instrument():
        return _dispatch("by_instrument")

    @bp.get("/api/stats/by-day")
    def by_day():
        return _dispatch("by_day")

    @bp.get("/api/stats/by-week")
    def by_week():
        return _dispatch("by_week")

    @bp.get("/api/stats/by-month")
    def by_month():
        return _dispatch("by_month")

    @bp.get("/api/stats/by-hour")
    def by_hour():
        return _dispatch("by_hour")

    @bp.get("/api/stats/by-side")
    def by_side():
        return _dispatch("by_side")

    @bp.get("/api/stats/equity-curve")
    def equity_curve():
        return _dispatch("equity_curve")

    @bp.get("/api/stats/distribution")
    def distribution():
        return _dispatch("distribution")

    @bp.get("/api/stats/by-day-of-week")
    def by_day_of_week():
        return _dispatch("by_day_of_week")

    return bp
