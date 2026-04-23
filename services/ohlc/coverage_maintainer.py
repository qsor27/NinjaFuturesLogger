"""Coverage maintainer — replaces the post-import OHLC hook and
recent/week refresh jobs with a single scheduler-driven sweep.

Two entry points:
- coverage_maintainer_tick: runs every 30 min, active contracts, narrow
  windows targeted at keeping current data current.
- historical_sweep_tick: runs every 4h, active + winding_down contracts,
  wider windows targeted at backfilling reachable history.

Both accept an injected `fetch_fn` so tests can verify the call shape
without any network or DB side effects beyond the coverage table read.
"""

from pathlib import Path
from typing import Protocol

from db import connect
from logging_config import get_logger
from services.instruments import base_symbol, source_symbol
from services.ohlc.coverage_state import (
    list_coverage,
    refresh_instrument_coverage_state,
)

log = get_logger("ohlc.coverage_maintainer")


# Window widths in seconds per timeframe.
MAINTAINER_WINDOWS: dict[str, int] = {
    "1m": 2 * 86400,
    "5m": 2 * 86400,
    "15m": 2 * 86400,
    "1h": 7 * 86400,
}

SWEEP_WINDOWS: dict[str, int] = {
    "1m": 7 * 86400,
    "5m": 60 * 86400,
    "15m": 60 * 86400,
    "1h": 730 * 86400,
    "1d": 10 * 365 * 86400,
}


class FetchFn(Protocol):
    def __call__(
        self,
        *,
        db_path: Path | str,
        instrument: str,
        timeframe: str,
        start: int,
        end: int,
        trigger: str,
    ) -> None: ...


def coverage_maintainer_tick(
    *,
    db_path: Path | str,
    fetch_fn: FetchFn,
    now: int,
) -> None:
    _run(
        db_path=db_path,
        fetch_fn=fetch_fn,
        now=now,
        windows=MAINTAINER_WINDOWS,
        states=("active",),
        trigger="maintainer",
    )


def historical_sweep_tick(
    *,
    db_path: Path | str,
    fetch_fn: FetchFn,
    now: int,
) -> None:
    _run(
        db_path=db_path,
        fetch_fn=fetch_fn,
        now=now,
        windows=SWEEP_WINDOWS,
        states=("active", "winding_down"),
        trigger="sweep",
    )


def _run(
    *,
    db_path: Path | str,
    fetch_fn: FetchFn,
    now: int,
    windows: dict[str, int],
    states: tuple[str, ...],
    trigger: str,
) -> None:
    conn = connect(db_path)
    try:
        refresh_instrument_coverage_state(conn, now=now)
        rows = [r for r in list_coverage(conn) if r.state in states]
    finally:
        conn.close()

    for row in rows:
        # Skip only if neither source can resolve the root at all (no
        # continuous symbol and no contract template). A root with only a
        # continuous symbol still gets fetched — classify_window will
        # decide whether the suffixed contract is reachable.
        root = base_symbol(row.instrument)
        if (
            source_symbol(row.instrument, "yfinance") is None
            and source_symbol(row.instrument, "stooq") is None
            and source_symbol(root, "yfinance") is None
            and source_symbol(root, "stooq") is None
        ):
            log.info("skip unknown instrument", extra={"instrument": row.instrument})
            continue
        for tf, width in windows.items():
            end = now
            start = end - width
            try:
                fetch_fn(
                    db_path=db_path,
                    instrument=row.instrument,
                    timeframe=tf,
                    start=start,
                    end=end,
                    trigger=trigger,
                )
            except Exception:
                log.exception(
                    "coverage maintainer fetch failed",
                    extra={"instrument": row.instrument, "tf": tf},
                )
