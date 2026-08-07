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

    def _token_bucket():
        # None-tolerant: blueprint-level tests build the app without a
        # bucket; fetch_range treats None as "no throttle".
        return current_app.config.get("FTL_OHLC_TOKEN_BUCKET")

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

        # Provider-reach clamp: intraday timeframes have a hard provider
        # lookback cap (e.g. yfinance serves 1m only for the last ~30
        # days). Clamp `start` forward to the same floor fetch_range will
        # use; if the whole range is unreachable, return 409 so the UI
        # shows a clear message instead of queueing a job that drops
        # every gap as out_of_reach.
        import time as _time

        from services.ohlc.reach import PROVIDER_REACH, REACH_MARGIN_SECONDS, reach_floor

        floor = reach_floor(timeframe, now=int(_time.time()), margin=REACH_MARGIN_SECONDS)
        if floor is not None:
            if end <= floor:
                reach_days = PROVIDER_REACH[timeframe] // 86400
                return jsonify(
                    {
                        "error": "out_of_reach",
                        "detail": (
                            f"{timeframe} data is only available for the last "
                            f"{reach_days} days; requested window ends before that."
                        ),
                    }
                ), 409
            if start < floor:
                start = floor

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
        token_bucket = _token_bucket()

        def _run():
            return fetch_range(
                db_path=db_path,
                registry=registry,
                instrument=instrument,
                timeframe=timeframe,
                start=start,
                end=end,
                trigger="on_demand",
                token_bucket=token_bucket,
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

    @bp.get("/api/ohlc/attempts")
    def get_attempts():
        instrument = request.args.get("instrument")
        timeframe = request.args.get("timeframe")
        try:
            since = int(request.args.get("since", "0"))
        except ValueError:
            return jsonify({"error": "since must be int"}), 400
        try:
            limit = max(1, min(500, int(request.args.get("limit", "100"))))
        except ValueError:
            return jsonify({"error": "limit must be int"}), 400

        where = ["started_at >= ?"]
        params: list = [since]
        if instrument:
            where.append("instrument = ?")
            params.append(instrument)
        if timeframe:
            where.append("timeframe = ?")
            params.append(timeframe)
        clause = " AND ".join(where)
        conn = connect(_db_path())
        try:
            rows = conn.execute(
                f"SELECT * FROM fetch_attempts WHERE {clause} ORDER BY started_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            by_attempt = {r["id"]: {**dict(r), "sources": []} for r in rows}
            if rows:
                ids = list(by_attempt.keys())
                placeholders = ",".join(["?"] * len(ids))
                sources = conn.execute(
                    f"SELECT * FROM fetch_source_attempts"
                    f" WHERE attempt_id IN ({placeholders}) ORDER BY id",
                    ids,
                ).fetchall()
                for s in sources:
                    by_attempt[s["attempt_id"]]["sources"].append(dict(s))
        finally:
            conn.close()
        return jsonify({"attempts": list(by_attempt.values())})

    @bp.get("/api/ohlc/gaps")
    def get_gaps():
        from services.ohlc.gap_reports import list_reports

        state = request.args.get("state", "open")
        if state not in ("open", "abandoned", "resolved", "all"):
            return jsonify({"error": "invalid state"}), 400
        conn = connect(_db_path())
        try:
            rows = list_reports(conn, state=None if state == "all" else state)
        finally:
            conn.close()
        return jsonify({"gaps": [dict(r) for r in rows]})

    @bp.post("/api/ohlc/gaps/<int:gap_id>/retry")
    def post_gap_retry(gap_id: int):
        import time as _t

        from services.ohlc.fetcher import fetch_range
        from services.ohlc.gap_reports import reset_for_retry

        conn = connect(_db_path())
        try:
            row = conn.execute(
                "SELECT instrument, timeframe, gap_start, gap_end"
                " FROM ohlc_gap_reports WHERE id = ?",
                (gap_id,),
            ).fetchone()
            if row is None:
                return jsonify({"error": "not found"}), 404
            conn.execute("BEGIN")
            reset_for_retry(conn, gap_id=gap_id, now=int(_t.time()))
            conn.execute("COMMIT")
        finally:
            conn.close()

        pool = _pool()
        jobs = _jobs()
        registry = _registry()
        db_path = _db_path()
        token_bucket = _token_bucket()
        instrument = row["instrument"]
        timeframe = row["timeframe"]
        gap_start = row["gap_start"]
        gap_end = row["gap_end"]

        def _run():
            return fetch_range(
                db_path=db_path,
                registry=registry,
                instrument=instrument,
                timeframe=timeframe,
                start=gap_start,
                end=gap_end,
                trigger="on_demand",
                token_bucket=token_bucket,
            )

        job_id = jobs.submit(
            pool,
            _run,
            meta={
                "gap_id": gap_id,
                "instrument": instrument,
                "timeframe": timeframe,
                "start": gap_start,
                "end": gap_end,
            },
        )
        return jsonify({"job_id": job_id, "gap_id": gap_id}), 202

    @bp.post("/api/ohlc/bars/delete")
    def post_delete_bars():
        """Delete bars in [start, end) for (instrument, timeframe).

        Useful when a provider wrote incorrect prices (wrong contract,
        bad source) and you want to wipe + refetch. The next fetch_range
        call (on_demand via the chart, or self_heal on its schedule) will
        repopulate.
        """
        from services.ohlc.gap_detection import timeframe_seconds
        from services.ohlc.store import delete_range

        body = request.get_json(silent=True) or {}
        instrument = body.get("instrument")
        timeframe = body.get("timeframe")
        try:
            start = int(body.get("start"))
            end = int(body.get("end"))
        except (TypeError, ValueError):
            return jsonify({"error": "start and end are required integers"}), 400
        if not isinstance(instrument, str) or not instrument:
            return jsonify({"error": "instrument is required"}), 400
        if not isinstance(timeframe, str):
            return jsonify({"error": "timeframe is required"}), 400
        try:
            timeframe_seconds(timeframe)
        except ValueError:
            return jsonify({"error": f"unknown timeframe: {timeframe}"}), 400
        if start >= end:
            return jsonify({"error": "start must be < end"}), 400

        conn = connect(_db_path())
        try:
            conn.execute("BEGIN")
            deleted = delete_range(
                conn,
                instrument=instrument,
                timeframe=timeframe,
                start=start,
                end=end,
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

        log.info(
            "deleted bars",
            extra={
                "instrument": instrument,
                "tf": timeframe,
                "start": start,
                "end": end,
                "rows": deleted,
            },
        )
        return jsonify({"ok": True, "deleted": deleted})

    return bp
