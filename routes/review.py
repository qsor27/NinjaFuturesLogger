import random
import time

from flask import Blueprint, jsonify, request

from db import connect
from logging_config import get_logger
from models.review import RevealFill, RevealPayload
from routes import db_path as _db_path
from services.review_deck import (
    REVIEW_TIMEFRAMES,
    card_bars,
    eligible_cards,
    find_position,
    net_pnl,
    order_deck,
    reveal_bars,
)
from services.review_store import (
    attempt_stats,
    create_session,
    end_session,
    has_attempt,
    record_attempt,
    session_exists,
    summary,
)

log = get_logger("http.review")


def build_review_blueprint() -> Blueprint:
    bp = Blueprint("review", __name__)

    @bp.post("/api/review/sessions")
    def post_session():
        sid = create_session(_db_path(), now=int(time.time()))
        return jsonify({"session_id": sid}), 201

    @bp.get("/api/review/next-card")
    def get_next_card():
        try:
            sid = int(request.args.get("session_id", ""))
        except ValueError:
            return jsonify({"error": "session_id must be an integer"}), 400
        if not session_exists(_db_path(), sid):
            return jsonify({"error": "session not found"}), 404
        cards = eligible_cards(_db_path())
        if not cards:
            return "", 204
        ordered = order_deck(cards, attempt_stats(_db_path()), random.Random())
        return jsonify({"card": ordered[0].model_dump()})

    @bp.get("/api/review/cards/<entry_execution_id>/bars")
    def get_card_bars(entry_execution_id: str):
        timeframe = request.args.get("timeframe", "1m")
        if timeframe not in REVIEW_TIMEFRAMES:
            return jsonify({"error": f"unsupported timeframe: {timeframe}"}), 400
        revealed = request.args.get("revealed") == "1"
        found = find_position(_db_path(), entry_execution_id)
        if found is None:
            return jsonify({"error": "card not found"}), 404
        position, _fills = found

        if revealed:
            try:
                sid = int(request.args.get("session_id", ""))
            except ValueError:
                return jsonify({"error": "session_id must be an integer"}), 400
            if not has_attempt(_db_path(), sid, entry_execution_id):
                return jsonify({"error": "call first, then reveal"}), 403
            if position.exit_time is None:
                return jsonify({"error": "position still open"}), 409

        conn = connect(_db_path())
        try:
            if revealed:
                bars = reveal_bars(
                    conn,
                    instrument=position.instrument,
                    timeframe=timeframe,
                    entry_ts=position.entry_time,
                    exit_time=position.exit_time,
                )
            else:
                bars = card_bars(
                    conn,
                    instrument=position.instrument,
                    timeframe=timeframe,
                    entry_ts=position.entry_time,
                )
        finally:
            conn.close()
        if not revealed and not bars:
            return jsonify({"error": "no pre-entry bars for this card"}), 404
        return jsonify(
            {
                "instrument": position.instrument,
                "timeframe": timeframe,
                "bars": [b.model_dump() for b in bars],
            }
        )

    @bp.post("/api/review/attempts")
    def post_attempt():
        body = request.get_json(silent=True) or {}
        call = body.get("call")
        entry_execution_id = body.get("entry_execution_id")
        session_id = body.get("session_id")
        if call not in ("valid", "invalid"):
            return jsonify({"error": "call must be 'valid' or 'invalid'"}), 400
        if not isinstance(entry_execution_id, str) or not isinstance(session_id, int):
            return jsonify({"error": "session_id (int) and entry_execution_id (str) required"}), 400
        if not session_exists(_db_path(), session_id):
            return jsonify({"error": "session not found"}), 404
        found = find_position(_db_path(), entry_execution_id)
        if found is None:
            return jsonify({"error": "card not found"}), 404
        position, fills = found
        if position.exit_time is None:
            return jsonify({"error": "position still open"}), 409

        pnl = net_pnl(position)
        attempt_id = record_attempt(
            _db_path(),
            session_id=session_id,
            account=position.account,
            instrument=position.instrument,
            entry_execution_id=entry_execution_id,
            call=call,
            outcome_pnl=pnl,
            now=int(time.time()),
        )
        reveal = RevealPayload(
            net_pnl=pnl,
            dollars_pnl=position.dollars_pnl,
            commission=position.commission,
            exit_time=position.exit_time,
            exit_fills=[
                RevealFill(time=f.timestamp, price=f.price, side=f.side, quantity=f.quantity)
                for f in fills
                if f.entry_exit == "Exit"
            ],
        )
        return jsonify({"attempt_id": attempt_id, "reveal": reveal.model_dump()}), 201

    @bp.post("/api/review/sessions/<int:session_id>/end")
    def post_end(session_id: int):
        if not end_session(_db_path(), session_id, now=int(time.time())):
            return jsonify({"error": "session not found"}), 404
        return jsonify(
            {
                "session": summary(_db_path(), session_id=session_id).model_dump(),
                "all_time": summary(_db_path()).model_dump(),
            }
        )

    return bp
