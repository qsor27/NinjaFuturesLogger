import random
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
        base_cooldown_seconds: int,
        base_cooldown_rate_limit_seconds: int | None = None,
        max_cooldown_seconds: int | None = None,
        backoff_multiplier: float = 2.0,
        jitter_fraction: float = 0.15,
    ) -> None:
        # Seed an RNG per source so runs are reproducible and two
        # sources that trip simultaneously re-probe at different times.
        rng = random.Random(hash(source.name)).random
        breaker = CircuitBreaker(
            name=source.name,
            failure_threshold=failure_threshold,
            base_cooldown_seconds=base_cooldown_seconds,
            base_cooldown_rate_limit_seconds=base_cooldown_rate_limit_seconds,
            max_cooldown_seconds=max_cooldown_seconds,
            backoff_multiplier=backoff_multiplier,
            jitter_fraction=jitter_fraction,
            clock=self._clock,
            rng=rng,
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

    Breaker tuning:
    - yfinance: 3 misc failures trips; base 5m cooldown on server/network.
      Rate-limit backoff is deliberately conservative (plan 19): 1h on the
      first 429, escalating 4× per re-open to a 12h ceiling (1h → 4h → 12h).
      A 429 means Yahoo already flagged us as a bot; probing back in 15m is
      how you get escalated to a full-day IP ban.
    - stooq:    3 misc failures trips; base 10m cooldown on server/network;
      30m on rate-limit; 2× escalation per re-open; 6h cap.
    """
    reg = SourceRegistry(clock=clock)
    reg.register(
        YfinanceSource(),
        failure_threshold=3,
        base_cooldown_seconds=300,
        base_cooldown_rate_limit_seconds=3600,
        max_cooldown_seconds=12 * 3600,
        backoff_multiplier=4.0,
        jitter_fraction=0.15,
    )
    reg.register(
        StooqSource(),
        failure_threshold=3,
        base_cooldown_seconds=600,
        base_cooldown_rate_limit_seconds=1800,
        max_cooldown_seconds=21600,
        backoff_multiplier=2.0,
        jitter_fraction=0.15,
    )
    return reg
