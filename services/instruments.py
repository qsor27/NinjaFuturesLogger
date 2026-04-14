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


def get_multiplier(instrument: str) -> float:
    """Dollars per point for the instrument. Unknown symbols return 1.0."""
    cfg = _REGISTRY.get(base_symbol(instrument))
    if cfg is None:
        return 1.0
    return cfg.multiplier


def source_symbol(instrument: str, source: str) -> str | None:
    cfg = _REGISTRY.get(base_symbol(instrument))
    if cfg is None:
        return None
    if source == "yfinance":
        return cfg.sources.yfinance.continuous
    if source == "stooq":
        return cfg.sources.stooq.continuous
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
