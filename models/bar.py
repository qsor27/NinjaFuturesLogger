from typing import Literal

from models.base import StrictModel

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
FetchStatus = Literal[
    "cached", "ok", "partial", "all_sources_unavailable", "no_source_for_timeframe"
]
Outcome = Literal["ok", "failed", "skipped"]


class Bar(StrictModel):
    instrument: str
    timeframe: Timeframe
    time: int  # unix seconds, UTC
    open: float
    high: float
    low: float
    close: float
    volume: int  # 0 if source did not provide one, never None
    source: str  # which adapter wrote it: 'yfinance', 'stooq', ...


class AttemptRecord(StrictModel):
    source: str
    outcome: Outcome
    count: int  # bars returned (0 for failed/skipped)
    error: str | None


class FetchResult(StrictModel):
    status: FetchStatus
    bars_added: int
    attempts: list[AttemptRecord]
