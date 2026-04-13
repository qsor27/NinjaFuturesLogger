"""Instrument metadata stub.

Plan 16 replaces this with a JSON-backed registry. Until then, this module
holds the multipliers plan 11 needs for dollars_pnl. When you migrate to
the JSON registry, delete this file and update the imports in
services/positions.py.
"""

_MULTIPLIERS: dict[str, float] = {
    # CME equity index futures
    "ES": 50.0,
    "MES": 5.0,
    "NQ": 20.0,
    "MNQ": 2.0,
    "RTY": 50.0,
    "M2K": 5.0,
    "YM": 5.0,
    "MYM": 0.50,
    # CME energies
    "CL": 1000.0,
    "MCL": 100.0,
    "NG": 10000.0,
    "QG": 2500.0,
    "RB": 42000.0,
    "HO": 42000.0,
    # CME metals
    "GC": 100.0,
    "MGC": 10.0,
    "SI": 5000.0,
    "SIL": 1000.0,
    "HG": 25000.0,
    "MHG": 2500.0,
    # CME interest rates (partial)
    "ZN": 1000.0,
    "ZB": 1000.0,
    "ZF": 1000.0,
    "ZT": 2000.0,
    # CME FX
    "6E": 125000.0,
    "6B": 62500.0,
    "6J": 12500000.0,
}


def base_symbol(instrument: str) -> str:
    """Strip any trailing contract-month suffix like ' SEP25'."""
    return instrument.split(" ", 1)[0]


def get_multiplier(instrument: str) -> float:
    """Dollars per point for the instrument. Unknown symbols return 1.0."""
    return _MULTIPLIERS.get(base_symbol(instrument), 1.0)


# ---------------------------------------------------------------------------
# Plan 14 additions — timeframes, per-source symbol tables, default session
# Plan 16 will replace this whole module with a JSON-backed registry.
# ---------------------------------------------------------------------------

from dataclasses import dataclass

DEFAULT_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "1d")

_YFINANCE_SYMBOLS: dict[str, str] = {
    "ES": "ES=F", "MES": "MES=F",
    "NQ": "NQ=F", "MNQ": "MNQ=F",
    "RTY": "RTY=F", "M2K": "M2K=F",
    "YM": "YM=F", "MYM": "MYM=F",
    "CL": "CL=F", "MCL": "MCL=F",
    "GC": "GC=F", "MGC": "MGC=F",
    "SI": "SI=F", "SIL": "SIL=F",
    "ZN": "ZN=F", "ZB": "ZB=F",
    "6E": "6E=F", "6B": "6B=F",
}

_STOOQ_SYMBOLS: dict[str, str] = {
    "ES": "es.f", "MES": "mes.f",
    "NQ": "nq.f", "MNQ": "mnq.f",
    "RTY": "rty.f", "M2K": "m2k.f",
    "YM": "ym.f", "MYM": "mym.f",
    "CL": "cl.f", "MCL": "mcl.f",
    "GC": "gc.f", "MGC": "mgc.f",
    "SI": "si.f", "SIL": "sil.f",
    "ZN": "zn.f", "ZB": "zb.f",
    "6E": "6e.f", "6B": "6b.f",
}

_SOURCE_TABLES: dict[str, dict[str, str]] = {
    "yfinance": _YFINANCE_SYMBOLS,
    "stooq": _STOOQ_SYMBOLS,
}


def source_symbol(instrument: str, source: str) -> str | None:
    """Map a canonical NT instrument key to a per-source symbol.

    Returns None if either the source is unknown or the instrument is not
    in the source's table. Adapters skip instruments they cannot identify.
    Plan 16 replaces this with the instruments.json registry.
    """
    table = _SOURCE_TABLES.get(source)
    if table is None:
        return None
    return table.get(base_symbol(instrument))


@dataclass(frozen=True)
class SessionCalendar:
    """A one-day-repeating session description.

    Plan 14 ships a single default (CME futures: 17:00 → 16:00 next day,
    with a 16:00–17:00 daily break, all in America/Chicago) which gap
    detection consults to avoid flagging the overnight close as missing.
    Plan 16 replaces this with per-instrument JSON-driven calendars.
    """
    timezone: str
    open: str               # "HH:MM" local
    close: str              # "HH:MM" local
    daily_break_start: str  # "HH:MM" local; "" disables
    daily_break_end: str    # "HH:MM" local; "" disables


_DEFAULT_CME_SESSION = SessionCalendar(
    timezone="America/Chicago",
    open="17:00",
    close="16:00",
    daily_break_start="16:00",
    daily_break_end="17:00",
)


def default_session(_instrument: str) -> SessionCalendar:
    """Return the default trading session for the given instrument.

    Plan 14 returns the CME futures session for every instrument. Plan 16
    will dispatch on `instrument` against the JSON registry.
    """
    return _DEFAULT_CME_SESSION
