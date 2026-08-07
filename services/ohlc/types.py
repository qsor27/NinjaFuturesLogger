"""Shared OHLC callable contracts."""

from pathlib import Path
from typing import Protocol


class FetchFn(Protocol):
    """Scheduler-facing fetch callable (app.py's `_fetch` wrapper around
    fetch_range). Injected into the coverage-maintainer and self-heal
    ticks so tests can verify the call shape without network or DB
    side effects."""

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
