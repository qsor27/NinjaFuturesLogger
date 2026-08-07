"""Provider reach table — how far back each timeframe can be fetched.

Values are the maximum lookback window yfinance will serve in a single
request for each interval, in seconds. `reach_floor` is the single
clamp formula shared by the fetcher, the chart-fetch route, the
data-health route, and the gap-report writer.
"""

PROVIDER_REACH: dict[str, int] = {
    # Yahoo's own error says: "1m data ... must be within the last 30 days."
    # Per-request chunk size is a separate concept (7 days) — handled inside
    # YfinanceSource.fetch. This constant is the total historical window.
    "1m": 30 * 86400,
    "5m": 60 * 86400,
    "15m": 60 * 86400,
    "1h": 730 * 86400,
    "1d": 40 * 365 * 86400,
    "1wk": 40 * 365 * 86400,
    "1mo": 40 * 365 * 86400,
}

# Requests that start exactly at the provider's reach boundary get rejected
# ("requested range must be within the last N days") because time advances
# between gap computation and the provider's check. Call sites that are
# about to *fetch* pass this as `margin` to stay inside the boundary.
REACH_MARGIN_SECONDS = 3600


def reach_floor(timeframe: str, *, now: int, margin: int = 0) -> int | None:
    """Earliest timestamp the provider can serve for `timeframe` at `now`.

    Returns None when reach is unlimited: unknown timeframe, or reach of
    a year and beyond (1h/daily+ — tests use 1970-era timestamps that
    must never be silently dropped).
    """
    reach = PROVIDER_REACH.get(timeframe)
    if reach is None or reach >= 365 * 86400:
        return None
    return now - reach + margin
