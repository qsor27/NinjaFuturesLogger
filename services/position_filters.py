from dataclasses import dataclass

from models.browsing import Outcome
from models.position import Position
from services.outcomes import classify_outcome


@dataclass(frozen=True)
class PositionFilter:
    account: str | None = None
    instrument: str | None = None
    side: str | None = None           # "Long" | "Short"
    outcome: Outcome | None = None    # "winner" | "loser" | "scratch" | "open"
    entry_time_min: int | None = None
    entry_time_max: int | None = None


def apply_filters(
    positions: list[Position],
    filter_: PositionFilter,
) -> list[Position]:
    """Pure function: compose all filter predicates with AND."""
    def _keep(p: Position) -> bool:
        if filter_.account is not None and p.account != filter_.account:
            return False
        if filter_.instrument is not None and p.instrument != filter_.instrument:
            return False
        if filter_.side is not None and p.side != filter_.side:
            return False
        if filter_.outcome is not None and classify_outcome(p) != filter_.outcome:
            return False
        if filter_.entry_time_min is not None and p.entry_time < filter_.entry_time_min:
            return False
        if filter_.entry_time_max is not None and p.entry_time > filter_.entry_time_max:
            return False
        return True

    return [p for p in positions if _keep(p)]


def paginate(
    positions: list[Position],
    *,
    page: int,
    page_size: int,
) -> tuple[list[Position], int]:
    """Return (slice, total_count). Clamps `page` to >= 1."""
    total = len(positions)
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 1
    start = (page - 1) * page_size
    end = start + page_size
    return positions[start:end], total
