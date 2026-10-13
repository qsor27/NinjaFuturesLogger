"""Entry-method classification (Setup Gate spec §12a).

The NinjaTrader Setup Gate tags its entry fills in the CSV `Name` column:
`GateMktNextOpen` / `GateLmtNextOpen`, with a `CT` suffix when the trader confirmed the
arm against the hourly trend (e.g. `GateLmtNextOpenCT`). These strings must stay in sync
with `ninjascript/Gate/GateRuntimeTypes.cs` (`GateEntryNames`).
"""

import re

from models.position import EntryMethod, TrendAlignment

GATE_MARKET_ORDER_NAME = "GateMktNextOpen"
GATE_LIMIT_ORDER_NAME = "GateLmtNextOpen"
COUNTER_TREND_SUFFIX = "CT"

_GATE_NAME = re.compile(r"^Gate(?P<kind>Mkt|Lmt)NextOpen(?P<ct>CT)?$")


def classify_entry_method(order_name: str | None) -> EntryMethod:
    """Map an entry fill's order name to how the position was entered."""
    if not order_name:
        return "unknown"
    match = _GATE_NAME.match(order_name)
    if match is None:
        return "manual"
    return "market_next_open" if match.group("kind") == "Mkt" else "limit_next_open"


def is_counter_trend(order_name: str | None) -> bool:
    """True when the gate entry was armed against the hourly trend (CT-tagged name)."""
    if not order_name:
        return False
    match = _GATE_NAME.match(order_name)
    return match is not None and match.group("ct") is not None


def classify_trend_alignment(order_name: str | None) -> TrendAlignment:
    """Gate entries are with or against the hourly trend; anything else wasn't gated."""
    if not order_name or _GATE_NAME.match(order_name) is None:
        return "not_gated"
    return "counter_trend" if is_counter_trend(order_name) else "with_trend"
