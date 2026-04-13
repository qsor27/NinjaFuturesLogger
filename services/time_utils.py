from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

EXCHANGE_TZ = ZoneInfo("America/Chicago")
ROLLOVER = time(16, 0)


def compute_session_date(ts_utc: datetime) -> date:
    """Map a UTC timestamp to its CME trading session date.

    The CME session rolls over at 16:00 America/Chicago; any timestamp at
    or after 16:00 local belongs to the *next* calendar day's session.
    DST is handled by `zoneinfo` because we attach a real timezone before
    comparing.

    Glossary entry: doc 02 -> "Trading session", "Session date".
    """
    if ts_utc.tzinfo is None:
        raise ValueError("compute_session_date requires a timezone-aware datetime")
    local = ts_utc.astimezone(EXCHANGE_TZ)
    if local.time() >= ROLLOVER:
        return (local + timedelta(days=1)).date()
    return local.date()


def resolve_current_trade_date(now_local: datetime) -> date:
    """Map a timezone-aware *local-exchange* datetime to its CME trade date.

    Mirrors `compute_session_date` but takes an already-localized datetime so
    the archival job can decide "is this file date < today's trade date?"
    without a UTC round-trip.
    """
    if now_local.tzinfo is None:
        raise ValueError("resolve_current_trade_date requires a timezone-aware datetime")
    if now_local.time() >= ROLLOVER:
        return (now_local + timedelta(days=1)).date()
    return now_local.date()
