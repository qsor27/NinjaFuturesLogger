from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from models.browsing import Outcome
from models.position import Position
from services.outcomes import classify_outcome
from services.time_utils import compute_session_date


@dataclass(frozen=True)
class PositionFilter:
    account: str | None = None
    instrument: str | None = None
    side: str | None = None  # "Long" | "Short"
    outcome: Outcome | None = None  # "winner" | "loser" | "scratch" | "open"
    entry_time_min: int | None = None
    entry_time_max: int | None = None
    session_date: date | None = None  # plan 15: calendar-cell click target
    # New drill-down fields (2026-04-16):
    session_date_from: date | None = None
    session_date_to: date | None = None
    day_of_week: int | None = None       # 0=Mon … 4=Fri
    hour_of_day: int | None = None       # 0..23
    hour_tz: str | None = None           # IANA tz, required when hour_of_day is set
    trades_per_day: int | None = None    # positive int; post-filter aggregation


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
        if filter_.session_date is not None:
            sd = compute_session_date(datetime.fromtimestamp(p.entry_time, tz=UTC))
            if sd != filter_.session_date:
                return False
        if filter_.session_date_from is not None or filter_.session_date_to is not None:
            sd = compute_session_date(datetime.fromtimestamp(p.entry_time, tz=UTC))
            if filter_.session_date_from is not None and sd < filter_.session_date_from:
                return False
            if filter_.session_date_to is not None and sd > filter_.session_date_to:
                return False
        if filter_.day_of_week is not None:
            sd = compute_session_date(datetime.fromtimestamp(p.entry_time, tz=UTC))
            if sd.weekday() != filter_.day_of_week:
                return False
        if filter_.hour_of_day is not None:
            if filter_.hour_tz is None:
                raise ValueError("hour_of_day requires hour_tz")
            local = datetime.fromtimestamp(p.entry_time, tz=ZoneInfo(filter_.hour_tz))
            if local.hour != filter_.hour_of_day:
                return False
        return True

    survivors = [p for p in positions if _keep(p)]

    if filter_.trades_per_day is not None:
        counts: dict[date, int] = {}
        for p in survivors:
            sd = compute_session_date(datetime.fromtimestamp(p.entry_time, tz=UTC))
            counts[sd] = counts.get(sd, 0) + 1
        target = filter_.trades_per_day
        survivors = [
            p for p in survivors
            if counts[compute_session_date(datetime.fromtimestamp(p.entry_time, tz=UTC))] == target
        ]

    return survivors


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
