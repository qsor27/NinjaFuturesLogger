"""Entry-method classification (Setup Gate spec §12a).

The NinjaTrader Setup Gate names its entry orders with the constants below, and
ExecutionExporter writes the order name into the CSV `Name` column. These
strings must stay in sync with the NinjaScript gate.
"""

from models.position import EntryMethod

GATE_MARKET_ORDER_NAME = "GateMktNextOpen"
GATE_LIMIT_ORDER_NAME = "GateLmtNextOpen"


def classify_entry_method(order_name: str | None) -> EntryMethod:
    """Map an entry fill's order name to how the position was entered."""
    if not order_name:
        return "unknown"
    if order_name == GATE_MARKET_ORDER_NAME:
        return "market_next_open"
    if order_name == GATE_LIMIT_ORDER_NAME:
        return "limit_next_open"
    return "manual"
