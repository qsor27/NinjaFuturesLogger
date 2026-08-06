import math
from datetime import UTC, datetime

from models.bar import Bar
from services.instruments import (
    front_month_window,
    get_registry,
    parse_instrument,
    source_symbol,
)


def _lookup_error(symbol: str, detail) -> RuntimeError:
    """Build the error raised when yfinance's _ERRORS dict reports a lookup
    failure ('possibly delisted; no price data found', 'data not available
    for startTime=...'). Yahoo answered — it just has no bars for this
    symbol/range — so the error is classified `no_data`: the fetcher still
    falls through to the next source, but the circuit breaker must not
    count it as a provider outage (plan 18's 'other' class slow-trips,
    which let permanently-unfillable gaps keep yfinance open for hours).
    """
    from services.ohlc._classify import attach_classification

    err = RuntimeError(f"yfinance lookup failed for {symbol!r}: {detail}")
    attach_classification(err, failure_class="no_data")
    return err


def _download(symbol: str, *, start, end, interval):
    """Indirection so tests can monkeypatch without installing yfinance.

    Uses yf.Ticker.history() and checks yfinance.shared._ERRORS afterwards.
    Both yf.download() and Ticker.history() swallow lookup errors
    (e.g. YFTzMissingError for unrecognised symbols) — they log them and
    return an empty DataFrame instead of raising. This prevents the circuit
    breaker from recording a failure so stooq is never tried as a fallback.
    Detecting the error via _ERRORS and re-raising restores the spec
    contract: "if an adapter can't produce Bar objects from a response,
    it raises."

    Plan 18: HTTP/network errors from the underlying requests transport
    are caught and tagged with a FailureClassification so the breaker can
    escalate appropriately. A bad-symbol / no-data lookup (the _ERRORS
    path) is classified "no_data" — Yahoo answered, so it must not count
    toward tripping the breaker at all (see _lookup_error).
    """
    import requests
    import yfinance as yf  # deferred so the test suite never imports it
    import yfinance.shared as _yfs

    from services.ohlc._classify import attach_classification, classify_http_error

    _yfs._ERRORS.pop(symbol, None)  # clear any stale entry from a prior call

    try:
        df = yf.Ticker(symbol).history(
            start=start,
            end=end,
            interval=interval,
            auto_adjust=False,
        )
    except requests.HTTPError as http_err:
        cls, retry_after = classify_http_error(http_err)
        raise attach_classification(
            http_err, failure_class=cls, retry_after_seconds=retry_after
        ) from None
    except (requests.ConnectionError, requests.Timeout) as net_err:
        raise attach_classification(net_err, failure_class="network") from None

    if symbol in _yfs._ERRORS:
        raise _lookup_error(symbol, _yfs._ERRORS[symbol])

    return df


class YfinanceSource:
    """Primary OHLC source. Wraps the yfinance library.

    Front-month fallback: when a specific-contract symbol (e.g. MNQM26.CME)
    returns no data AND the requested window is entirely inside the contract's
    front-month window (see services.instruments.front_month_window), retry
    once with Yahoo's continuous symbol (e.g. MNQ=F). Bars sourced this way
    are tagged `source="yfinance-continuous"` so the trail distinguishes
    them from specific-contract bars.

    The fallback only applies to quarterly contracts (H/M/U/Z) where the
    continuous symbol provably tracks the same underlying during the window.
    """

    name = "yfinance"
    supported_timeframes = frozenset({"1m", "5m", "15m", "1h", "1d"})

    def fetch(self, instrument: str, timeframe: str, start: int, end: int) -> list[Bar]:
        if timeframe not in self.supported_timeframes:
            return []
        symbol = source_symbol(instrument, "yfinance")
        if symbol is None:
            return []

        fallback_symbol = _continuous_fallback_symbol(instrument, start, end)
        if fallback_symbol == symbol:
            # Already the continuous symbol — no fallback path to try.
            fallback_symbol = None

        try:
            bars = self._fetch_symbol(
                instrument, symbol, timeframe, start, end, source_tag="yfinance"
            )
        except RuntimeError:
            # _download raises RuntimeError only for the yfinance _ERRORS
            # path ("lookup failed / possibly delisted"). If a fallback is
            # available, retry there; otherwise re-raise so the breaker
            # counts this as a failure.
            if fallback_symbol is None:
                raise
            bars = []

        if bars or fallback_symbol is None:
            return bars

        return self._fetch_symbol(
            instrument,
            fallback_symbol,
            timeframe,
            start,
            end,
            source_tag="yfinance-continuous",
        )

    def _fetch_symbol(
        self,
        instrument: str,
        symbol: str,
        timeframe: str,
        start: int,
        end: int,
        *,
        source_tag: str,
    ) -> list[Bar]:
        # yfinance enforces a 7-day-per-request limit for 1m data. Chunk any
        # 1m range longer than that and concat — the fetcher still sees one
        # call per gap. Other intraday timeframes are served in a single
        # request at their native reach limits (5m/15m/1h: 60d / 730d).
        if timeframe == "1m":
            chunk_seconds = 7 * 86400
        else:
            chunk_seconds = None

        frames = []
        if chunk_seconds is None:
            start_dt = datetime.fromtimestamp(start, tz=UTC)
            end_dt = datetime.fromtimestamp(end, tz=UTC)
            frames.append(_download(symbol, start=start_dt, end=end_dt, interval=timeframe))
        else:
            cursor = start
            while cursor < end:
                chunk_end = min(cursor + chunk_seconds, end)
                frames.append(
                    _download(
                        symbol,
                        start=datetime.fromtimestamp(cursor, tz=UTC),
                        end=datetime.fromtimestamp(chunk_end, tz=UTC),
                        interval=timeframe,
                    )
                )
                cursor = chunk_end

        frames = [df for df in frames if df is not None and not df.empty]
        if not frames:
            return []

        bars: list[Bar] = []
        seen_ts: set[int] = set()
        for df in frames:
            for row in df.itertuples(index=True, name="Bar"):
                ts = int(row.Index.timestamp())
                if ts in seen_ts:
                    continue
                seen_ts.add(ts)
                volume = row.Volume
                if volume is None or (isinstance(volume, float) and math.isnan(volume)):
                    volume = 0
                bars.append(
                    Bar(
                        instrument=instrument,
                        timeframe=timeframe,
                        time=ts,
                        open=float(row.Open),
                        high=float(row.High),
                        low=float(row.Low),
                        close=float(row.Close),
                        volume=int(volume),
                        source=source_tag,
                    )
                )
        return bars


def _continuous_fallback_symbol(instrument: str, start: int, end: int) -> str | None:
    """Return the continuous Yahoo symbol if fallback is safe for this window.

    Safe means: the instrument is a specific quarterly contract, the registry
    has a continuous symbol for it, and [start, end) lies fully inside the
    contract's front-month window.
    """
    root, contract = parse_instrument(instrument)
    if contract is None:
        return None  # already continuous — no fallback available
    window = front_month_window(instrument)
    if window is None:
        return None
    w_start, w_end = window
    if start < w_start or end > w_end:
        return None
    cfg = get_registry().get(root)
    if cfg is None:
        return None
    return cfg.sources.yfinance.continuous
