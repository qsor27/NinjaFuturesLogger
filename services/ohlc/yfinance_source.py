import math
from datetime import UTC, datetime

from models.bar import Bar
from services.instruments import source_symbol


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
    """
    import yfinance as yf  # deferred so the test suite never imports it
    import yfinance.shared as _yfs

    _yfs._ERRORS.pop(symbol, None)  # clear any stale entry from a prior call

    df = yf.Ticker(symbol).history(
        start=start,
        end=end,
        interval=interval,
        auto_adjust=False,
    )

    if symbol in _yfs._ERRORS:
        raise RuntimeError(f"yfinance lookup failed for {symbol!r}: {_yfs._ERRORS[symbol]}")

    return df


class YfinanceSource:
    """Primary OHLC source. Wraps the yfinance library."""

    name = "yfinance"
    supported_timeframes = frozenset({"1m", "5m", "15m", "1h", "1d"})

    def fetch(self, instrument: str, timeframe: str, start: int, end: int) -> list[Bar]:
        if timeframe not in self.supported_timeframes:
            return []
        symbol = source_symbol(instrument, "yfinance")
        if symbol is None:
            return []

        start_dt = datetime.fromtimestamp(start, tz=UTC)
        end_dt = datetime.fromtimestamp(end, tz=UTC)
        df = _download(symbol, start=start_dt, end=end_dt, interval=timeframe)
        if df is None or df.empty:
            return []

        bars: list[Bar] = []
        for row in df.itertuples(index=True, name="Bar"):
            ts = int(row.Index.timestamp())
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
                    source="yfinance",
                )
            )
        return bars
