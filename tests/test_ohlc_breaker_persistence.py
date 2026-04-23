from pathlib import Path

from db import connect
from migrations import run_migrations
from services.ohlc.breaker_persistence import (
    load_breaker,
    persist_breaker,
)
from services.ohlc.circuit_breaker import CircuitBreaker


def _fresh_db(tmp_path):
    db = tmp_path / "t.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    conn.close()
    return db


def _breaker(name="yfinance", clock=lambda: 1000):
    return CircuitBreaker(
        name=name,
        failure_threshold=3,
        base_cooldown_seconds=60,
        clock=clock,
    )


def test_persist_then_load_roundtrip(tmp_path):
    db = _fresh_db(tmp_path)
    b = _breaker()

    class _E(Exception):
        pass

    b.record_failure(_E("boom"))
    b.record_failure(_E("boom"))
    b.record_failure(_E("boom"))  # trips it

    conn = connect(db)
    try:
        conn.execute("BEGIN")
        persist_breaker(conn, b, now=1234)
        conn.execute("COMMIT")
    finally:
        conn.close()

    # New breaker, load from DB.
    b2 = _breaker()
    assert b2.state == "closed"
    conn = connect(db)
    try:
        load_breaker(conn, b2)
    finally:
        conn.close()
    assert b2.state == "open"
    assert b2.consecutive_trips == b.consecutive_trips
    assert b2.next_retry_at == b.next_retry_at


def test_load_breaker_no_row_leaves_state_unchanged(tmp_path):
    db = _fresh_db(tmp_path)
    b = _breaker(name="stooq")
    conn = connect(db)
    try:
        load_breaker(conn, b)
    finally:
        conn.close()
    assert b.state == "closed"  # default unchanged
