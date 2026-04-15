import csv
from datetime import UTC, datetime
from io import StringIO

from models.bar import Bar
from services.instruments import source_symbol

_STOOQ_INTERVALS: dict[str, str] = {"1d": "d"}


def _http_get(url: str) -> str:
    """Indirection so tests can monkeypatch without hitting the network.

    Plan 18: HTTP and connect errors are caught and tagged with a
    FailureClassification so the breaker can escalate appropriately on
    rate-limits vs 5xx vs connection failures.
    """
    import requests  # deferred so the test suite never imports it

    from services.ohlc._classify import attach_classification, classify_http_error

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except requests.HTTPError as http_err:
        cls, retry_after = classify_http_error(http_err)
        raise attach_classification(
            http_err, failure_class=cls, retry_after_seconds=retry_after
        ) from None
    except (requests.ConnectionError, requests.Timeout) as net_err:
        raise attach_classification(net_err, failure_class="network") from None
    return resp.text


def _iso_to_unix(iso_date: str) -> int:
    return int(datetime.fromisoformat(iso_date).replace(tzinfo=UTC).timestamp())


class StooqSource:
    """Fallback OHLC source. Plain HTTP CSV from stooq.com.

    Conservative: only daily bars are declared supported until per-instrument
    intraday verification (doc 14, open question 3) extends this set.
    """

    name = "stooq"
    supported_timeframes = frozenset({"1d"})

    def fetch(self, instrument: str, timeframe: str, start: int, end: int) -> list[Bar]:
        if timeframe not in self.supported_timeframes:
            return []
        symbol = source_symbol(instrument, "stooq")
        if symbol is None:
            return []

        interval = _STOOQ_INTERVALS[timeframe]
        url = f"https://stooq.com/q/d/l/?s={symbol}&i={interval}"
        text = _http_get(url)
        if not text or not text.strip():
            return []

        reader = csv.DictReader(StringIO(text))
        bars: list[Bar] = []
        for row in reader:
            try:
                ts = _iso_to_unix(row["Date"])
            except (KeyError, ValueError):
                continue
            if ts < start or ts >= end:
                continue
            try:
                o = float(row["Open"])
                h = float(row["High"])
                lo = float(row["Low"])
                c = float(row["Close"])
            except (KeyError, ValueError):
                continue
            vol_raw = (row.get("Volume") or "").strip()
            try:
                volume = int(vol_raw) if vol_raw else 0
            except ValueError:
                volume = 0
            bars.append(
                Bar(
                    instrument=instrument,
                    timeframe=timeframe,
                    time=ts,
                    open=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=volume,
                    source="stooq",
                )
            )
        return bars
