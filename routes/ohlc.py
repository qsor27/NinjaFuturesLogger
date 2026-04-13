from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger
from services.ohlc.gap_detection import timeframe_seconds
from services.ohlc.store import read_range

log = get_logger("http.ohlc")


def build_ohlc_blueprint() -> Blueprint:
    bp = Blueprint("ohlc", __name__)

    def _db_path():
        return current_app.config["FTL_DB_PATH"]

    def _pool():
        return current_app.config["FTL_OHLC_POOL"]

    def _jobs():
        return current_app.config["FTL_OHLC_JOBS"]

    def _registry():
        return current_app.config["FTL_OHLC_REGISTRY"]

    @bp.get("/api/chart/<instrument>")
    def get_chart(instrument: str):
        timeframe = request.args.get("timeframe", "1m")
        try:
            timeframe_seconds(timeframe)
        except ValueError:
            return jsonify({"error": f"unknown timeframe: {timeframe}"}), 400
        try:
            start = int(request.args.get("start", "0"))
            end = int(request.args.get("end", "0"))
        except ValueError:
            return jsonify({"error": "start and end must be integers"}), 400

        conn = connect(_db_path())
        try:
            bars = read_range(
                conn,
                instrument=instrument,
                timeframe=timeframe,
                start=start,
                end=end,
            )
        finally:
            conn.close()
        return jsonify({
            "instrument": instrument,
            "timeframe": timeframe,
            "bars": [b.model_dump() for b in bars],
        })

    @bp.post("/api/chart/<instrument>/fetch")
    def post_chart_fetch(instrument: str):
        body = request.get_json(silent=True) or {}
        timeframe = body.get("timeframe")
        try:
            start = int(body.get("start"))
            end = int(body.get("end"))
        except (TypeError, ValueError):
            return jsonify({"error": "start and end are required integers"}), 400
        if not isinstance(timeframe, str):
            return jsonify({"error": "timeframe is required"}), 400
        try:
            timeframe_seconds(timeframe)
        except ValueError:
            return jsonify({"error": f"unknown timeframe: {timeframe}"}), 400

        # Deferred import: routes/ohlc.py must not import the fetcher at
        # module load time, because Rule 1 says "no route synchronously
        # invokes the fetcher." Importing it inside the closure that
        # *submits* it to the pool is fine — the route still returns
        # immediately with a job ID.
        from services.ohlc.fetcher import fetch_range

        pool = _pool()
        jobs = _jobs()
        registry = _registry()
        db_path = _db_path()

        def _run():
            return fetch_range(
                db_path=db_path,
                registry=registry,
                instrument=instrument,
                timeframe=timeframe,
                start=start,
                end=end,
            )

        job_id = jobs.submit(pool, _run, meta={
            "instrument": instrument,
            "timeframe": timeframe,
            "start": start,
            "end": end,
        })
        return jsonify({"job_id": job_id}), 202

    @bp.get("/api/ohlc/jobs/<job_id>")
    def get_job(job_id: str):
        snap = _jobs().status(job_id)
        if snap.get("state") == "not_found":
            return jsonify({"error": "not found"}), 404
        return jsonify(snap)

    @bp.get("/api/ohlc/sources")
    def get_sources():
        return jsonify({"sources": _registry().status_snapshots()})

    return bp
