"""Instrument registry — the one source of truth for instrument metadata.

Replaces the hardcoded tables that were in services/instruments.py through plan
14. Reads and writes `data/config/instruments.json`. First load on a missing or
empty file writes DEFAULT_SEED (derived from plan 11/14 constants) out to disk
so existing Docker installs keep the same multipliers and symbol maps.
"""

import json
import os
import threading
from pathlib import Path

from models.settings import InstrumentConfig

_MULTIPLIERS: dict[str, float] = {
    "ES": 50.0, "MES": 5.0, "NQ": 20.0, "MNQ": 2.0,
    "RTY": 50.0, "M2K": 5.0, "YM": 5.0, "MYM": 0.50,
    "CL": 1000.0, "MCL": 100.0, "NG": 10000.0, "QG": 2500.0,
    "RB": 42000.0, "HO": 42000.0,
    "GC": 100.0, "MGC": 10.0, "SI": 5000.0, "SIL": 1000.0,
    "HG": 25000.0, "MHG": 2500.0,
    "ZN": 1000.0, "ZB": 1000.0, "ZF": 1000.0, "ZT": 2000.0,
    "6E": 125000.0, "6B": 62500.0, "6J": 12500000.0,
}

_YFINANCE_SYMBOLS: dict[str, str] = {
    "ES": "ES=F", "MES": "MES=F", "NQ": "NQ=F", "MNQ": "MNQ=F",
    "RTY": "RTY=F", "M2K": "M2K=F", "YM": "YM=F", "MYM": "MYM=F",
    "CL": "CL=F", "MCL": "MCL=F",
    "GC": "GC=F", "MGC": "MGC=F", "SI": "SI=F", "SIL": "SIL=F",
    "ZN": "ZN=F", "ZB": "ZB=F", "6E": "6E=F", "6B": "6B=F",
}

_STOOQ_SYMBOLS: dict[str, str] = {
    "ES": "es.f", "MES": "mes.f", "NQ": "nq.f", "MNQ": "mnq.f",
    "RTY": "rty.f", "M2K": "m2k.f", "YM": "ym.f", "MYM": "mym.f",
    "CL": "cl.f", "MCL": "mcl.f",
    "GC": "gc.f", "MGC": "mgc.f", "SI": "si.f", "SIL": "sil.f",
    "ZN": "zn.f", "ZB": "zb.f", "6E": "6e.f", "6B": "6b.f",
}

_DISPLAY_NAMES: dict[str, str] = {
    "ES": "E-mini S&P 500", "MES": "Micro E-mini S&P 500",
    "NQ": "E-mini Nasdaq-100", "MNQ": "Micro E-mini Nasdaq-100",
    "RTY": "E-mini Russell 2000", "M2K": "Micro E-mini Russell 2000",
    "YM": "E-mini Dow", "MYM": "Micro E-mini Dow",
    "CL": "Crude Oil", "MCL": "Micro Crude Oil",
    "NG": "Natural Gas", "QG": "E-mini Natural Gas",
    "RB": "RBOB Gasoline", "HO": "Heating Oil",
    "GC": "Gold", "MGC": "Micro Gold",
    "SI": "Silver", "SIL": "Micro Silver",
    "HG": "Copper", "MHG": "Micro Copper",
    "ZN": "10-Year T-Note", "ZB": "30-Year T-Bond",
    "ZF": "5-Year T-Note", "ZT": "2-Year T-Note",
    "6E": "Euro FX", "6B": "British Pound", "6J": "Japanese Yen",
}

_TICK_SIZES: dict[str, float] = {
    "ES": 0.25, "MES": 0.25, "NQ": 0.25, "MNQ": 0.25,
    "RTY": 0.10, "M2K": 0.10, "YM": 1.0, "MYM": 1.0,
    "CL": 0.01, "MCL": 0.01, "NG": 0.001, "QG": 0.005,
    "RB": 0.0001, "HO": 0.0001,
    "GC": 0.10, "MGC": 0.10, "SI": 0.005, "SIL": 0.005,
    "HG": 0.0005, "MHG": 0.0005,
    "ZN": 0.015625, "ZB": 0.03125, "ZF": 0.0078125, "ZT": 0.0078125,
    "6E": 0.00005, "6B": 0.0001, "6J": 0.0000005,
}

_DEFAULT_SESSION = {
    "timezone": "America/Chicago",
    "open": "17:00",
    "close": "16:00",
    "daily_break_start": "16:00",
    "daily_break_end": "17:00",
}


def _build_default_seed() -> dict[str, dict]:
    seed: dict[str, dict] = {}
    for symbol, mult in _MULTIPLIERS.items():
        seed[symbol] = {
            "display_name": _DISPLAY_NAMES.get(symbol, symbol),
            "multiplier": mult,
            "tick_size": _TICK_SIZES.get(symbol, 0.01),
            "sources": {
                "yfinance": {
                    "continuous": _YFINANCE_SYMBOLS.get(symbol),
                    "contract_template": None,
                },
                "stooq": {
                    "continuous": _STOOQ_SYMBOLS.get(symbol),
                    "contract_template": None,
                },
            },
            "session": dict(_DEFAULT_SESSION),
        }
    return seed


DEFAULT_SEED: dict[str, dict] = _build_default_seed()


class InstrumentRegistry:
    """Load and persist `instruments.json`. Thread-safe via module-level lock."""

    _lock = threading.Lock()

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._data: dict[str, InstrumentConfig] = {}
        self._loaded = False

    def load(self) -> None:
        with self._lock:
            self._load_locked()

    def _load_locked(self) -> None:
        if not self._path.exists() or self._path.stat().st_size == 0:
            self._seed_to_disk()
        raw_text = self._path.read_text(encoding="utf-8")
        try:
            raw = json.loads(raw_text) if raw_text.strip() else {}
        except json.JSONDecodeError:
            raw = {}
        if not raw:
            self._seed_to_disk()
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        self._data = {
            symbol: InstrumentConfig(**payload) for symbol, payload in raw.items()
        }
        self._loaded = True

    def _seed_to_disk(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._write_raw(DEFAULT_SEED)

    def _write_raw(self, raw: dict[str, dict]) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(str(tmp), str(self._path))

    def _flush(self) -> None:
        raw = {
            symbol: self._data[symbol].model_dump()
            for symbol in sorted(self._data)
        }
        self._write_raw(raw)

    def get(self, symbol: str) -> InstrumentConfig | None:
        if not self._loaded:
            self.load()
        return self._data.get(symbol)

    def list(self) -> list[tuple[str, InstrumentConfig]]:
        if not self._loaded:
            self.load()
        return [(s, self._data[s]) for s in sorted(self._data)]

    def put(self, symbol: str, cfg: InstrumentConfig) -> None:
        with self._lock:
            if not self._loaded:
                self._load_locked()
            self._data[symbol] = cfg
            self._flush()

    def delete(self, symbol: str) -> None:
        with self._lock:
            if not self._loaded:
                self._load_locked()
            if symbol not in self._data:
                raise KeyError(symbol)
            del self._data[symbol]
            self._flush()
