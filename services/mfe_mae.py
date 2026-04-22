"""MFE/MAE computation — pure derived view over positions + bars.

Takes an already-built Position and the 1m bars that cover its window;
returns an MfeMaeResult. No DB access, no fetch_range calls, no globals.
Rule 6 of CLAUDE.md: OHLC read-only in services like this one.
"""

from __future__ import annotations

from pathlib import Path

from db import connect
from models.bar import Bar
from models.mfe_mae import MfeMaeResult
from models.position import Position
from services.instruments import get_multiplier
from services.ohlc.gap_detection import expected_slot_count, timeframe_seconds
from services.ohlc.store import read_range
from services.outcomes import classify_outcome


def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def compute_mfe_mae(position: Position, bars: list[Bar]) -> MfeMaeResult | None:
    """Compute MFE/MAE dollars, coverage, and one of {capture,risk}_efficiency.

    Returns None iff the position is still open (exit_time is None).
    For closed positions, always returns a result — partial bar coverage is
    reflected in the `coverage` field, not by refusing to compute.
    """
    if position.exit_time is None:
        return None

    entry = position.entry_time
    exit_ = position.exit_time
    entry_price = position.entry_price
    qty = position.quantity
    mult = get_multiplier(position.instrument)
    sign = 1 if position.side == "Long" else -1

    stride = timeframe_seconds("1m")
    in_window = [b for b in bars if b.time < exit_ and b.time + stride > entry]

    mfe = 0.0
    mae = 0.0
    mfe_time = entry
    mae_time = entry
    mfe_price = entry_price  # price that produced the MFE peak
    mae_price = entry_price  # price that produced the MAE trough

    for b in in_window:
        # For a Long: favorable move uses bar.high, adverse uses bar.low.
        # For a Short: favorable move uses bar.low, adverse uses bar.high.
        if sign == 1:
            favorable_edge = b.high
            adverse_edge = b.low
            favorable = (favorable_edge - entry_price) * qty * mult
            adverse = (adverse_edge - entry_price) * qty * mult
        else:
            favorable_edge = b.low
            adverse_edge = b.high
            favorable = (entry_price - favorable_edge) * qty * mult
            adverse = (entry_price - adverse_edge) * qty * mult
        if favorable > mfe:
            mfe = favorable
            mfe_time = b.time
            mfe_price = favorable_edge
        if adverse < mae:
            mae = adverse
            mae_time = b.time
            mae_price = adverse_edge

    # Coverage: bars present / expected session slots in the window.
    expected = expected_slot_count(position.instrument, "1m", entry, exit_)
    if expected <= 0:
        coverage = 1.0 if in_window else 0.0
    else:
        coverage = min(1.0, len(in_window) / expected)

    outcome = classify_outcome(position)
    realized = position.dollars_pnl
    capture_eff: float | None = None
    risk_eff: float | None = None
    if outcome == "winner" and mfe > 0 and realized is not None:
        capture_eff = _clamp(realized / mfe, 0.0, 1.0)
    elif outcome == "loser" and mae < 0 and realized is not None:
        risk_eff = _clamp(1.0 - abs(realized) / abs(mae), 0.0, 1.0)
    # scratch or winner-with-zero-mfe or loser-with-zero-mae → both stay None.

    return MfeMaeResult(
        mfe_dollars=mfe,
        mae_dollars=mae,
        mfe_time=mfe_time,
        mae_time=mae_time,
        mfe_price=mfe_price,
        mae_price=mae_price,
        coverage=coverage,
        capture_efficiency=capture_eff,
        risk_efficiency=risk_eff,
    )


def load_and_compute(db_path: Path | str, position: Position) -> MfeMaeResult | None:
    """Load 1m bars from the bars table for position's window and compute.

    Closes the DB connection on return. Returns None if the position is
    still open; otherwise returns a best-effort MfeMaeResult (coverage may
    be < 1.0 if bars haven't been fetched yet).
    """
    if position.exit_time is None:
        return None
    # Widen the DB query so bars opening just before entry (and whose 1m span
    # still overlaps the trade window) are fetched — compute_mfe_mae filters
    # them precisely. Without the widening a sub-minute trade entirely inside
    # one bar would see zero bars and report 0% coverage.
    stride = timeframe_seconds("1m")
    conn = connect(db_path)
    try:
        bars = read_range(
            conn,
            instrument=position.instrument,
            timeframe="1m",
            start=max(0, position.entry_time - stride + 1),
            end=position.exit_time,
        )
    finally:
        conn.close()
    return compute_mfe_mae(position, bars)
