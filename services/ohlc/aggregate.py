"""Read-time 4h view transform over stored 1h bars.

4h is the one allowed upscale in the OHLC subsystem. Bars are never
persisted — this helper is called when a chart route asks for tf=4h.
Blocks align to CME session opens (17:00 CT). Partial blocks (fewer
than 4 hours present) are silently dropped — the chart shows a gap.

The 16:00-17:00 daily break falls naturally because there is no 1h
bar in that hour; any block that straddles it will be partial and
therefore omitted.
"""

from models.bar import Bar

_BLOCK_SECONDS = 4 * 3600
_STEP = 3600
_REF_1700_CT = 1776290400  # 2026-04-14T22:00:00Z == 17:00 America/Chicago (CDT)


def derive_4h(bars_1h: list[Bar]) -> list[Bar]:
    if not bars_1h:
        return []
    by_time = {b.time: b for b in bars_1h}
    instrument = bars_1h[0].instrument

    first = min(by_time)
    last = max(by_time)
    # Align `first` down to the nearest 4h block boundary from the reference.
    offset = (first - _REF_1700_CT) % _BLOCK_SECONDS
    start = first - offset

    out: list[Bar] = []
    while start <= last:
        block_times = [start + i * _STEP for i in range(4)]
        block_bars = [by_time.get(t) for t in block_times]
        if all(b is not None for b in block_bars):
            out.append(_rollup(instrument, start, block_bars))  # type: ignore[arg-type]
        start += _BLOCK_SECONDS
    return out


def _rollup(instrument: str, start_ts: int, bars: list[Bar]) -> Bar:
    return Bar(
        instrument=instrument,
        timeframe="4h",
        time=start_ts,
        open=bars[0].open,
        high=max(b.high for b in bars),
        low=min(b.low for b in bars),
        close=bars[-1].close,
        volume=sum(b.volume for b in bars),
        source="derived-1h",
    )
