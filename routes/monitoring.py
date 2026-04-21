import time

from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger
from services.ohlc.gap_detection import (
    classify_window,
    expected_session_slots,
    find_gaps,
    timeframe_seconds,
)
from services.ohlc.reach import PROVIDER_REACH
from services.ohlc.store import list_times

log = get_logger("http.monitoring")

CANONICAL_TIMEFRAMES = ["1m", "5m", "15m", "1h", "1d", "1wk", "1mo"]
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
                        conn,
                        instrument=instrument,
                        timeframe=tf,
                        start=start,
                        end=now,
                        now=now,
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

        # Clamp the gap-listing window to the provider reach for this
        # timeframe — listing gaps that no source can ever serve only
        # invites the user to click "Fetch Missing" on something that
        # will fail. Callers (chart + data-health) both expect the
        # returned `start` / `end` to reflect what was actually scanned.
        reach = PROVIDER_REACH.get(timeframe)
        # Only clamp intraday timeframes — daily/weekly/monthly reach is
        # effectively unlimited at the provider, and unit tests pass
        # 1970-era timestamps that shouldn't be silently dropped.
        if reach is not None and reach < 365 * 86400:
            reach_floor = now - reach
            scan_start = max(start, reach_floor)
        else:
            scan_start = start

        conn = connect(_db_path())
        try:
            if scan_start >= end:
                gaps: list[tuple[int, int]] = []
                expected: list[int] = []
                present: list[int] = []
            else:
                gaps = find_gaps(
                    conn, instrument=instrument, timeframe=timeframe, start=scan_start, end=end
                )
                expected = expected_session_slots(instrument, timeframe, scan_start, end)
                present = list_times(
                    conn, instrument=instrument, timeframe=timeframe, start=scan_start, end=end
                )
        finally:
            conn.close()

        return jsonify(
            {
                "instrument": instrument,
                "timeframe": timeframe,
                "start": scan_start,
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

    @bp.get("/api/data-health/maintainer")
    def data_health_maintainer():
        services = _services()
        scheduler = services.scheduler
        job = scheduler.get_job("ohlc_coverage_maintainer")
        history = services._job_history.get("ohlc_coverage_maintainer", [])
        last = next(iter(history), None) if history else None
        token_bucket = current_app.config.get("FTL_OHLC_TOKEN_BUCKET")
        tb_stats = token_bucket.stats() if token_bucket is not None else {}
        next_run_time = getattr(job, "next_run_time", None) if job else None
        return jsonify(
            {
                "next_run_at": (next_run_time.timestamp() if next_run_time else None),
                "last_run_at": last["started_at"] if last else None,
                "last_run_status": last["status"] if last else None,
                "token_bucket": tb_stats,
            }
        )

    return bp


def _cell_status(conn, *, instrument: str, timeframe: str, start: int, end: int, now: int) -> str:
    """Compute completeness status for one instrument × timeframe cell."""
    summary = classify_window(
        conn,
        instrument=instrument,
        timeframe=timeframe,
        start=start,
        end=end,
        now=now,
    )
    if summary["expected"] == 0:
        return "session_closed"
    if summary["out_of_reach"] == summary["expected"]:
        return "out_of_reach"
    if summary["missing"] == 0 and summary["present"] > 0:
        return "complete"
    if summary["present"] == 0 and summary["out_of_reach"] < summary["expected"]:
        return "missing"
    return "partial"
