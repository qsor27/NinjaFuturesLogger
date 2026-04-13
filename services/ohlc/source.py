from typing import Protocol, runtime_checkable

from models.bar import Bar


@runtime_checkable
class OhlcSource(Protocol):
    """Per-source adapter contract.

    Each implementation lives in its own file under services/ohlc/.
    Adapters MUST return a normalized, UTC-timestamped list[Bar]; raising is
    the only legal way to report partial or malformed data.
    """

    name: str
    supported_timeframes: frozenset[str]

    def fetch(
        self,
        instrument: str,
        timeframe: str,
        start: int,  # unix seconds, UTC, inclusive
        end: int,  # unix seconds, UTC, exclusive
    ) -> list[Bar]: ...
