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
