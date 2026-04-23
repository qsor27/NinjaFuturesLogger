from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger
from services.chart_defaults import get_defaults
from services.ohlc.aggregate import derive_4h
from services.ohlc.gap_detection import timeframe_seconds
from services.ohlc.store import read_range

log = get_logger("http.ohlc")
CANONICAL_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]


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
            if timeframe == "4h":
                bars_1h = read_range(
                    conn,
                    instrument=instrument,
                    timeframe="1h",
                    start=start,
                    end=end,
                )
                bars = derive_4h(bars_1h)
            else:
                bars = read_range(
                    conn,
                    instrument=instrument,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                )
        finally:
            conn.close()
        return jsonify(
            {
                "instrument": instrument,
                "timeframe": timeframe,
                "bars": [b.model_dump() for b in bars],
            }
        )

    @bp.get("/api/chart/<instrument>/timeframes-available")
    def get_timeframes_available(instrument: str):
        # Read-only count query against the bars table. Reads only — never
        # fetches. (Plan 13 load-bearing rule 2.)
        conn = connect(_db_path())
        try:
            rows = conn.execute(
                "SELECT timeframe, COUNT(*) AS bar_count FROM bars "
                "WHERE instrument = ? GROUP BY timeframe",
                (instrument,),
            ).fetchall()
        finally:
            conn.close()
        counts = {r["timeframe"]: int(r["bar_count"]) for r in rows}
        timeframes = [
            {
                "timeframe": tf,
                "available": counts.get(tf, 0) > 0,
                "count": counts.get(tf, 0),
            }
            for tf in CANONICAL_TIMEFRAMES
        ]
        defaults = get_defaults(_db_path())
        return jsonify(
            {
                "instrument": instrument,
                "timeframes": timeframes,
                "default_timeframe": defaults["default_timeframe"],
                "volume_visible_default": defaults["volume_visible_default"],
            }
        )

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
        if timeframe == "4h":
            return jsonify(
                {"error": "4h candles are derived from 1h bars and cannot be fetched directly"}
            ), 400

        # Provider-reach clamp: yfinance only serves 1m data for the last
        # ~30 days (similar caps for other intraday timeframes). Out-of-
        # reach fetches produce a RuntimeError that trips the circuit
        # breaker and blocks subsequent fetches until cooldown. Clamp
        # `start` forward; if the whole range is unreachable, return 409
        # so the UI can show a clear message.
        import time as _time

        from services.ohlc.reach import PROVIDER_REACH

        reach = PROVIDER_REACH.get(timeframe)
        # Only clamp intraday timeframes (reach < 1 year). Daily/weekly/
        # monthly are effectively unlimited at yfinance, and unit tests
        # use synthetic 1970-era timestamps that shouldn't be blocked.
        if reach is not None and reach < 365 * 86400:
            reach_floor = int(_time.time()) - reach
            if end <= reach_floor:
                return jsonify(
                    {
                        "error": "out_of_reach",
                        "detail": (
                            f"{timeframe} data is only available for the last "
                            f"{reach // 86400} days; requested window ends before that."
                        ),
                    }
                ), 409
            if start < reach_floor:
                start = reach_floor

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
                trigger="on_demand",
            )

        job_id = jobs.submit(
            pool,
            _run,
            meta={
                "instrument": instrument,
                "timeframe": timeframe,
                "start": start,
                "end": end,
            },
        )
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
