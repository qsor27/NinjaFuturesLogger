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
