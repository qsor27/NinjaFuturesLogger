import time

from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger
from services.ohlc.gap_detection import _expected_slots, find_gaps, timeframe_seconds
from services.ohlc.store import list_times

log = get_logger("http.monitoring")

CANONICAL_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
DATA_HEALTH_LOOKBACK_DAYS = 7
ACTIVE_INSTRUMENTS_LOOKBACK_DAYS = 90


def build_monitoring_blueprint() -> Blueprint:
    bp = Blueprint("monitoring", __name__)

    def _db_path() -> str:
        return current_app.config["FTL_DB_PATH"]

    def _services():
        return current_app.config["BACKGROUND_SERVICES"]

    # ------------------------------------------------------------------ #
    # Data health                                                         #
    # ------------------------------------------------------------------ #

    @bp.get("/api/data-health/completeness")
    def data_health_completeness():
        days = int(request.args.get("days", str(DATA_HEALTH_LOOKBACK_DAYS)))
        now = int(time.time())
        start = now - days * 86400
        cutoff = now - ACTIVE_INSTRUMENTS_LOOKBACK_DAYS * 86400

        conn = connect(_db_path())
        try:
            rows = conn.execute(
                "SELECT DISTINCT instrument FROM executions WHERE timestamp >= ? ORDER BY instrument",
                (cutoff,),
            ).fetchall()
            instruments = [r["instrument"] for r in rows]

            cells: dict[str, dict[str, str]] = {}
            for instrument in instruments:
                cells[instrument] = {}
                for tf in CANONICAL_TIMEFRAMES:
                    cells[instrument][tf] = _cell_status(
                        conn, instrument=instrument, timeframe=tf, start=start, end=now
                    )
        finally:
            conn.close()

        return jsonify(
            {
                "instruments": instruments,
                "timeframes": CANONICAL_TIMEFRAMES,
                "cells": cells,
                "window_start": start,
                "window_end": now,
                "days": days,
            }
        )

    @bp.get("/api/data-health/missing/<instrument>/<timeframe>")
    def data_health_missing(instrument: str, timeframe: str):
        try:
            timeframe_seconds(timeframe)
        except ValueError:
            return jsonify({"error": f"unknown timeframe: {timeframe}"}), 400

        now = int(time.time())
        default_days = DATA_HEALTH_LOOKBACK_DAYS
        start = int(request.args.get("start", now - default_days * 86400))
        end = int(request.args.get("end", now))

        conn = connect(_db_path())
        try:
            gaps = find_gaps(conn, instrument=instrument, timeframe=timeframe, start=start, end=end)
            expected = _expected_slots(instrument, timeframe, start, end)
            present = list_times(
                conn, instrument=instrument, timeframe=timeframe, start=start, end=end
            )
        finally:
            conn.close()

        return jsonify(
            {
                "instrument": instrument,
                "timeframe": timeframe,
                "start": start,
                "end": end,
                "expected_slots": len(expected),
                "present_bars": len(present),
                "gaps": [{"start": g[0], "end": g[1]} for g in gaps],
            }
        )

    # ------------------------------------------------------------------ #
    # System health                                                       #
    # ------------------------------------------------------------------ #

    @bp.get("/api/system/health")
    def system_health():
        snap = _services().system_health_snapshot()
        return jsonify(snap)

    @bp.post("/api/system/run-job/<job_id>")
    def run_job(job_id: str):
        ok = _services().run_job_now(job_id)
        if not ok:
            return jsonify({"error": f"job '{job_id}' not found"}), 404
        return jsonify({"ok": True, "job_id": job_id})

    return bp


def _cell_status(conn, *, instrument: str, timeframe: str, start: int, end: int) -> str:
    """Compute completeness status for one instrument × timeframe cell."""
    expected = _expected_slots(instrument, timeframe, start, end)
    if not expected:
        return "session_closed"
    gaps = find_gaps(conn, instrument=instrument, timeframe=timeframe, start=start, end=end)
    if not gaps:
        return "complete"
    present = list_times(conn, instrument=instrument, timeframe=timeframe, start=start, end=end)
    return "missing" if not present else "partial"
