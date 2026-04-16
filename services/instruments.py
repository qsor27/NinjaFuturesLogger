"""Instrument metadata — thin delegator over InstrumentRegistry.

Plan 11 (positions.py) imports get_multiplier and base_symbol. Plan 14 (ohlc
adapters, gap_detection, app.py) imports DEFAULT_TIMEFRAMES, source_symbol,
SessionCalendar, and default_session. All six names are preserved by this
module; their bodies now read from the JSON-backed InstrumentRegistry that
plan 16 shipped. DEFAULT_TIMEFRAMES stays as a module constant because
app.py reads it at import time via `from services.instruments import
DEFAULT_TIMEFRAMES`.
"""

from dataclasses import dataclass
from pathlib import Path

from services.instrument_registry import InstrumentRegistry

DEFAULT_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "1d")

_DEFAULT_JSON_PATH = Path("data/config/instruments.json")


@dataclass(frozen=True)
class SessionCalendar:
    timezone: str
    open: str
    close: str
    daily_break_start: str
    daily_break_end: str


_REGISTRY = InstrumentRegistry(_DEFAULT_JSON_PATH)


def get_registry() -> InstrumentRegistry:
    return _REGISTRY


def set_registry_path(path: Path | str) -> None:
    """Bind the registry to a specific path. Called by create_app once
    Config has been loaded so the registry points at the real data_dir."""
    global _REGISTRY
    _REGISTRY = InstrumentRegistry(path)


def base_symbol(instrument: str) -> str:
    """Strip any trailing contract-month suffix like ' SEP25'."""
    return instrument.split(" ", 1)[0]


def parse_instrument(instrument: str) -> tuple[str, str | None]:
    """Split a NinjaTrader instrument string into (root, contract_suffix).

    Accepts "MNQ" or "MNQ JUN26". Raises ValueError for empty strings or
    strings with more than one space. The contract suffix is whatever follows
    the single space — rendering into a source symbol happens in source_symbol().
    """
    if not instrument:
        raise ValueError("empty instrument string")
    parts = instrument.split(" ")
    if len(parts) == 1:
        return parts[0], None
    if len(parts) == 2:
        return parts[0], parts[1]
    raise ValueError(f"malformed instrument: {instrument!r}")


def get_multiplier(instrument: str) -> float:
    """Dollars per point for the instrument. Unknown symbols return 1.0."""
    cfg = _REGISTRY.get(base_symbol(instrument))
    if cfg is None:
        return 1.0
    return cfg.multiplier


def effective_commission(instrument: str, execution_commission: float, quantity: int) -> float:
    """Return the commission to use for P&L calculations.

    Rule: use NT-reported commission if > 0; otherwise fall back to
    commission_per_contract × quantity from the instrument registry.
    A fallback of 0 means 'not configured' (e.g. sim accounts).
    """
    if execution_commission > 0:
        return execution_commission
    cfg = _REGISTRY.get(base_symbol(instrument))
    if cfg is None or cfg.commission_per_contract <= 0:
        return 0.0
    return cfg.commission_per_contract * quantity


_MONTH_CODES: dict[str, str] = {
    "JAN": "F",
    "FEB": "G",
    "MAR": "H",
    "APR": "J",
    "MAY": "K",
    "JUN": "M",
    "JUL": "N",
    "AUG": "Q",
    "SEP": "U",
    "OCT": "V",
    "NOV": "X",
    "DEC": "Z",
}


def _render_contract_template(template: str, *, root: str, contract: str) -> str | None:
    """Render a contract_template like '{ROOT}{M}{YY}.CME' given a 5-char
    contract suffix like 'JUN26'. Returns None if the suffix is malformed.
    """
    if len(contract) != 5:
        return None
    month_word = contract[:3].upper()
    year = contract[3:]
    if month_word not in _MONTH_CODES or not year.isdigit():
        return None
    return template.format(ROOT=root, M=_MONTH_CODES[month_word], YY=year)


def source_symbol(instrument: str, source: str) -> str | None:
    root, contract = parse_instrument(instrument)
    cfg = _REGISTRY.get(root)
    if cfg is None:
        return None
    if source == "yfinance":
        mapping = cfg.sources.yfinance
    elif source == "stooq":
        mapping = cfg.sources.stooq
    else:
        return None
    if contract is None:
        return mapping.continuous
    if mapping.contract_template:
        return _render_contract_template(mapping.contract_template, root=root, contract=contract)
    return None


_DEFAULT_CME_SESSION = SessionCalendar(
    timezone="America/Chicago",
    open="17:00",
    close="16:00",
    daily_break_start="16:00",
    daily_break_end="17:00",
)


def default_session(instrument: str) -> SessionCalendar:
    cfg = _REGISTRY.get(base_symbol(instrument))
    if cfg is None:
        return _DEFAULT_CME_SESSION
    s = cfg.session
    return SessionCalendar(
        timezone=s.timezone,
        open=s.open,
        close=s.close,
        daily_break_start=s.daily_break_start,
        daily_break_end=s.daily_break_end,
    )


# CME Equity Index full-closure holidays — days where no daily bar will
# ever exist for MNQ/NQ/ES/MES/etc. Early-close days (day-after-Thanksgiving,
# Christmas Eve, Jul 3 when partial) are deliberately excluded because a 1d
# bar IS produced for those sessions. Published on cmegroup.com "Holiday
# Calendar - Equity Index"; refresh annually. Covers 2024-2028.
CME_EQUITY_FULL_CLOSURE_DATES: frozenset[str] = frozenset(
    {
        # 2024
        "2024-01-01",  # New Year's Day
        "2024-01-15",  # Martin Luther King Jr. Day
        "2024-02-19",  # Presidents' Day
        "2024-03-29",  # Good Friday
        "2024-05-27",  # Memorial Day
        "2024-06-19",  # Juneteenth
        "2024-07-04",  # Independence Day
        "2024-09-02",  # Labor Day
        "2024-11-28",  # Thanksgiving
        "2024-12-25",  # Christmas
        # 2025
        "2025-01-01",  # New Year's Day
        "2025-01-20",  # Martin Luther King Jr. Day
        "2025-02-17",  # Presidents' Day
        "2025-04-18",  # Good Friday
        "2025-05-26",  # Memorial Day
        "2025-06-19",  # Juneteenth
        "2025-07-04",  # Independence Day
        "2025-09-01",  # Labor Day
        "2025-11-27",  # Thanksgiving
        "2025-12-25",  # Christmas
        # 2026
        "2026-01-01",  # New Year's Day
        "2026-01-19",  # Martin Luther King Jr. Day
        "2026-02-16",  # Presidents' Day
        "2026-04-03",  # Good Friday
        "2026-05-25",  # Memorial Day
        "2026-06-19",  # Juneteenth
        "2026-07-03",  # Independence Day (observed; Jul 4 is Saturday)
        "2026-09-07",  # Labor Day
        "2026-11-26",  # Thanksgiving
        "2026-12-25",  # Christmas
        # 2027
        "2027-01-01",  # New Year's Day
        "2027-01-18",  # Martin Luther King Jr. Day
        "2027-02-15",  # Presidents' Day
        "2027-03-26",  # Good Friday
        "2027-05-31",  # Memorial Day
        "2027-06-18",  # Juneteenth (observed; Jun 19 is Saturday)
        "2027-07-05",  # Independence Day (observed; Jul 4 is Sunday)
        "2027-09-06",  # Labor Day
        "2027-11-25",  # Thanksgiving
        "2027-12-24",  # Christmas (observed; Dec 25 is Saturday)
        # 2028
        "2028-01-17",  # Martin Luther King Jr. Day (Jan 1 is Saturday; not observed on Mon Jan 3)
        "2028-02-21",  # Presidents' Day
        "2028-04-14",  # Good Friday
        "2028-05-29",  # Memorial Day
        "2028-06-19",  # Juneteenth
        "2028-07-04",  # Independence Day
        "2028-09-04",  # Labor Day
        "2028-11-23",  # Thanksgiving
        "2028-12-25",  # Christmas
    }
)


def is_full_closure(instrument: str, ts: int) -> bool:
    """Return True if the given UTC-midnight daily slot falls on a CME
    equity-index full closure day. `ts` is expected to be a UTC-aligned
    daily slot emitted by gap_detection._expected_slots — it represents
    the trade date in UTC calendar terms (e.g. 2026-02-16 00:00 UTC =
    Monday 2026-02-16 trade date), which is what yfinance stamps too.
    Do NOT convert to session-local time here: a midnight UTC slot maps
    to the previous local evening in any US timezone and would off-by-one
    the match. Plan 16's instrument registry will expand this to per-venue
    calendars later.
    """
    from datetime import UTC, datetime

    del instrument  # reserved for per-venue calendars in plan 16
    utc_date = datetime.fromtimestamp(ts, tz=UTC).date()
    return utc_date.isoformat() in CME_EQUITY_FULL_CLOSURE_DATES
