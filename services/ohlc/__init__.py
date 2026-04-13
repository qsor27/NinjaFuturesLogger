"""OHLC pipeline: per-source adapters, circuit breaker, fetcher, store, jobs.

Nothing outside this package may see raw source data (pandas DataFrames,
Stooq CSV rows, naive datetimes). Adapters return list[Bar].
"""
