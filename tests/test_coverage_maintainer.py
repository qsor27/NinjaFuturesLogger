import json
from pathlib import Path

from db import connect
from migrations import run_migrations
from services.ohlc.coverage_maintainer import (
    MAINTAINER_WINDOWS,
    SWEEP_WINDOWS,
    coverage_maintainer_tick,
    historical_sweep_tick,
)
from services.ohlc.coverage_state import (
    refresh_instrument_coverage_state,
    retire_now,
)

# Registry restoration is handled by the autouse fixture in tests/conftest.py.


def _insert_exec(conn, instrument, ts):
    conn.execute(
        "INSERT INTO executions (nt_execution_id, account, instrument, timestamp,"
        " side, original_action, quantity, price, commission, entry_exit,"
        " source_filename, imported_at) "
        "VALUES (?, 'sim', ?, ?, 'Buy', 'Buy', 1, 100.0, 0.0, 'Entry', 'x.csv', 0)",
        (f"e-{instrument}-{ts}", instrument, ts),
    )


def test_maintainer_submits_active_contracts_only(tmp_path):
    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    now = 1_000_000_000
    _insert_exec(conn, "MNQ JUN26", now - 3600)
    _insert_exec(conn, "CL JUL26", now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    retire_now(conn, instrument="CL JUL26", now=now)
    conn.close()

    seen = []

    def fake_fetch(*, db_path, instrument, timeframe, start, end, trigger):
        seen.append((instrument, timeframe, start, end))

    coverage_maintainer_tick(db_path=db, fetch_fn=fake_fetch, now=now)
    instruments_called = {x[0] for x in seen}
    assert instruments_called == {"MNQ JUN26"}
    timeframes_called = {x[1] for x in seen}
    assert timeframes_called == set(MAINTAINER_WINDOWS.keys())


def test_sweep_uses_wider_windows(tmp_path):
    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    now = 1_000_000_000
    _insert_exec(conn, "MNQ JUN26", now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    conn.close()

    seen = []

    def fake_fetch(*, db_path, instrument, timeframe, start, end, trigger):
        seen.append((timeframe, end - start))

    historical_sweep_tick(db_path=db, fetch_fn=fake_fetch, now=now)
    windows_seen = {tf: w for tf, w in seen}
    for tf, w in SWEEP_WINDOWS.items():
        assert windows_seen[tf] == w
    for tf, w in MAINTAINER_WINDOWS.items():
        # sweep windows are always >= maintainer windows for the same tf
        if tf in SWEEP_WINDOWS:
            assert SWEEP_WINDOWS[tf] >= w


def test_maintainer_skips_instruments_with_no_contract_template(tmp_path):
    """A suffixed instrument whose registry has no contract_template
    ends up with source_symbol returning None for both sources.
    The maintainer should not submit fetches for it."""
    from services.instruments import set_registry_path

    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    now = 1_000_000_000
    _insert_exec(conn, "XYZ JUN26", now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    conn.close()

    path = tmp_path / "instruments.json"
    path.write_text(
        json.dumps(
            {
                "XYZ": {
                    "display_name": "Unknown",
                    "multiplier": 1.0,
                    "tick_size": 0.01,
                    "sources": {
                        "yfinance": {"continuous": None, "contract_template": None},
                        "stooq": {"continuous": None, "contract_template": None},
                    },
                    "session": {
                        "timezone": "America/Chicago",
                        "open": "17:00",
                        "close": "16:00",
                        "daily_break_start": "16:00",
                        "daily_break_end": "17:00",
                    },
                }
            }
        )
    )
    set_registry_path(path)

    seen = []

    def fake_fetch(*, db_path, instrument, timeframe, start, end, trigger):
        seen.append(instrument)

    coverage_maintainer_tick(db_path=db, fetch_fn=fake_fetch, now=now)
    assert seen == []
