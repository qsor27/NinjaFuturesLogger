from collections.abc import Callable, Iterator

from services.ohlc.circuit_breaker import CircuitBreaker
from services.ohlc.source import OhlcSource
from services.ohlc.stooq_source import StooqSource
from services.ohlc.yfinance_source import YfinanceSource


class SourceRegistry:
    """Ordered list of (source, breaker) pairs.

    The order in which `register()` is called determines the order in which
    the fetcher tries sources. Iteration filters to sources whose breaker
    currently allows a call AND that declare support for the requested
    timeframe (Rule 5: no upscaling).
    """

    def __init__(self, *, clock: Callable[[], int]) -> None:
        self._clock = clock
        self.entries: list[tuple[OhlcSource, CircuitBreaker]] = []

    def register(
        self,
        source: OhlcSource,
        *,
        failure_threshold: int,
        cooldown_seconds: int,
    ) -> None:
        breaker = CircuitBreaker(
            name=source.name,
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
            clock=self._clock,
        )
        self.entries.append((source, breaker))

    def sources_for(self, timeframe: str) -> Iterator[tuple[OhlcSource, CircuitBreaker]]:
        for source, breaker in self.entries:
            if timeframe not in source.supported_timeframes:
                continue
            if not breaker.allows():
                continue
            yield source, breaker

    def status_snapshots(self) -> list[dict]:
        return [breaker.status_snapshot() for _s, breaker in self.entries]


def build_default_registry(*, clock: Callable[[], int]) -> SourceRegistry:
    """Default order: yfinance primary, stooq fallback.

    The breaker parameters match doc 14:
    - yfinance: 3 failures, 600s cooldown
    - stooq:    3 failures, 1800s cooldown
    """
    reg = SourceRegistry(clock=clock)
    reg.register(YfinanceSource(), failure_threshold=3, cooldown_seconds=600)
    reg.register(StooqSource(), failure_threshold=3, cooldown_seconds=1800)
    return reg
