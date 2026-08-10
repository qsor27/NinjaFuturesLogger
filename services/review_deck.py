"""Review deck: eligibility, ordering, and hindsight-free bar cropping.

The functions at the top of this module are pure (no I/O, no DB access); DB
glue is appended below them. The load-bearing invariant: nothing returned by
the card-serving helpers may include price data at or after the crop
boundary (the start of the entry minute).
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


# --- DB glue (appended below the pure core) ---------------------------------

import sqlite3  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

from models.position import Fill  # noqa: E402
from services.execution_db import load_executions  # noqa: E402
from services.ohlc.store import read_range  # noqa: E402
from services.positions import build_positions_and_fills  # noqa: E402


def _coverage_count(conn: sqlite3.Connection, instrument: str, entry_ts: int) -> int:
    boundary = crop_boundary(entry_ts)
    row = conn.execute(
        "SELECT COUNT(*) FROM bars"
        " WHERE instrument = ? AND timeframe = '1m' AND time >= ? AND time < ?",
        (instrument, boundary - COVERAGE_WINDOW_SECONDS, boundary),
    ).fetchone()
    return int(row[0])


def _positions_with_fills(db_path: Path | str):
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for ex in load_executions(db_path):
        groups[(ex.account, ex.instrument)].append(ex)
    for key in sorted(groups):
        results, _issues = build_positions_and_fills(groups[key])
        yield from results


def eligible_cards(db_path: Path | str) -> list[ReviewCard]:
    """Closed positions whose entry has 1m coverage. Recomputed live: the deck
    grows as imports land and OHLC backfills — no deck table, no cache."""
    from db import connect  # local import: keep the pure core import-light

    conn = connect(db_path)
    try:
        cards: list[ReviewCard] = []
        for position, _fills in _positions_with_fills(db_path):
            if position.exit_time is None:
                continue
            if _coverage_count(conn, position.instrument, position.entry_time) < MIN_COVERAGE_BARS:
                continue
            cards.append(card_from_position(position))
        return cards
    finally:
        conn.close()


def find_position(
    db_path: Path | str, entry_execution_id: str
) -> tuple[Position, list[Fill]] | None:
    for position, fills in _positions_with_fills(db_path):
        if position.entry_execution_id == entry_execution_id:
            return position, fills
    return None


def card_bars(
    conn: sqlite3.Connection, *, instrument: str, timeframe: str, entry_ts: int
) -> list[Bar]:
    """Pre-call bars: completed bars strictly before the current bucket, plus
    the forming bucket synthesized from pre-boundary 1m bars. Never returns a
    bar whose interval contains or follows entry_ts."""
    boundary = crop_boundary(entry_ts)
    seconds = timeframe_seconds(timeframe)
    bucket_start = boundary - (boundary % seconds)
    full = read_range(
        conn,
        instrument=instrument,
        timeframe=timeframe,
        start=bucket_start - LOOKBACK_BARS * seconds,
        end=bucket_start,
    )
    minutes = read_range(
        conn, instrument=instrument, timeframe="1m", start=bucket_start, end=boundary
    )
    partial = synthesize_partial_bar(minutes, timeframe, boundary)
    return full + ([partial] if partial is not None else [])


def reveal_bars(
    conn: sqlite3.Connection,
    *,
    instrument: str,
    timeframe: str,
    entry_ts: int,
    exit_time: int,
) -> list[Bar]:
    """Post-call bars: the FULL window (lookback through close + buffer) so the
    client can setData() wholesale, replacing any synthesized partial bar with
    the real stored one."""
    boundary = crop_boundary(entry_ts)
    seconds = timeframe_seconds(timeframe)
    bucket_start = boundary - (boundary % seconds)
    return read_range(
        conn,
        instrument=instrument,
        timeframe=timeframe,
        start=bucket_start - LOOKBACK_BARS * seconds,
        end=exit_time + REVEAL_BUFFER_BARS * seconds,
    )
