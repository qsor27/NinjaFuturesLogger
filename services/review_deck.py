"""Review deck: eligibility, ordering, and hindsight-free bar cropping.

Pure functions live at the top (no sqlite, no Flask); DB glue is added at the
bottom of this module in a later task. The load-bearing invariant: nothing
returned by the card-serving helpers may include price data at or after the
crop boundary (the start of the entry minute).
"""

import random

from models.bar import Bar
from models.position import Position
from models.review import ReviewCard
from services.ohlc.gap_detection import timeframe_seconds

MIN_COVERAGE_BARS = 30
COVERAGE_WINDOW_SECONDS = 7200  # 2h before entry
LOOKBACK_BARS = 400  # pre-call history depth per timeframe
REVEAL_BUFFER_BARS = 30  # bars shown past position close on reveal
REVIEW_TIMEFRAMES = ("1m", "5m", "15m", "1h")


def crop_boundary(entry_ts: int) -> int:
    """Start of the entry minute. Bars at/after this instant are the future:
    even the 1m bar *containing* the fill closes after it and can leak the
    scalp's outcome, so it is excluded pre-call."""
    return entry_ts - (entry_ts % 60)


def net_pnl(position: Position) -> float:
    """Realized net PnL: gross dollars minus commissions. Closed positions only."""
    assert position.dollars_pnl is not None
    return position.dollars_pnl - position.commission


def card_from_position(position: Position) -> ReviewCard:
    return ReviewCard(
        account=position.account,
        instrument=position.instrument,
        entry_execution_id=position.entry_execution_id,
        entry_time=position.entry_time,
        side=position.side,
        quantity=position.quantity,
        entry_price=position.entry_price,
    )


def synthesize_partial_bar(one_minute_bars: list[Bar], timeframe: str, boundary: int) -> Bar | None:
    """The forming higher-timeframe bar as it looked at the crop boundary,
    aggregated from completed 1m bars inside the current bucket. None when the
    bucket has no completed 1m bars yet (boundary on the bucket edge)."""
    seconds = timeframe_seconds(timeframe)
    bucket_start = boundary - (boundary % seconds)
    src = [b for b in one_minute_bars if bucket_start <= b.time < boundary]
    if not src:
        return None
    return Bar(
        instrument=src[0].instrument,
        timeframe=timeframe,
        time=bucket_start,
        open=src[0].open,
        high=max(b.high for b in src),
        low=min(b.low for b in src),
        close=src[-1].close,
        volume=sum(b.volume for b in src),
        source="derived",
    )


def order_deck(
    cards: list[ReviewCard],
    stats: dict[str, tuple[int, int]],
    rng: random.Random,
) -> list[ReviewCard]:
    """Never-attempted cards first (shuffled), then least-recently-attempted
    first (ties shuffled) — a card cannot repeat within a session until
    everything else has cycled."""
    fresh: list[ReviewCard] = []
    seen: list[ReviewCard] = []
    for card in cards:
        count, _last = stats.get(card.entry_execution_id, (0, 0))
        (fresh if count == 0 else seen).append(card)
    rng.shuffle(fresh)
    seen.sort(key=lambda c: (stats[c.entry_execution_id][1], rng.random()))
    return fresh + seen
