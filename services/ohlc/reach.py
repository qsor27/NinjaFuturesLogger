"""Provider reach table — how far back each timeframe can be fetched.

Values are the maximum lookback window yfinance will serve in a single
request for each interval, in seconds. `is_out_of_reach` uses these to
distinguish "the provider cannot serve this" from "we haven't fetched
this yet" in gap detection and data-health.
"""

PROVIDER_REACH: dict[str, int] = {
    "1m": 7 * 86400,
    "5m": 60 * 86400,
    "15m": 60 * 86400,
    "1h": 730 * 86400,
    "1d": 40 * 365 * 86400,
    "1wk": 40 * 365 * 86400,
    "1mo": 40 * 365 * 86400,
}


def is_out_of_reach(timeframe: str, *, slot_ts: int, now: int) -> bool:
    """Return True if a slot at `slot_ts` is beyond the provider's reach at `now`."""
    if timeframe not in PROVIDER_REACH:
        raise ValueError(f"unknown timeframe: {timeframe}")
    return (now - slot_ts) > PROVIDER_REACH[timeframe]
