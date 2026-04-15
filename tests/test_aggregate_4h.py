from models.bar import Bar
from services.ohlc.aggregate import derive_4h


def _bar(ts: int, o: float, h: float, lo: float, c: float, v: int) -> Bar:
    return Bar(
        instrument="MNQ JUN26",
        timeframe="1h",
        time=ts,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=v,
        source="yfinance",
    )


BASE_1700_CT = 1776290400  # 2026-04-14T22:00:00Z = 2026-04-14 17:00 America/Chicago


def test_empty_input_returns_empty():
    assert derive_4h([]) == []


def test_single_complete_block_emits_one_bar():
    bars_1h = [
        _bar(BASE_1700_CT + h * 3600, 100 + h, 110 + h, 90 + h, 105 + h, 1000)
        for h in range(4)
    ]
    out = derive_4h(bars_1h)
    assert len(out) == 1
    b = out[0]
    assert b.timeframe == "4h"
    assert b.time == BASE_1700_CT
    assert b.open == 100
    assert b.high == 113
    assert b.low == 90
    assert b.close == 108
    assert b.volume == 4000
    assert b.source == "derived-1h"
    assert b.instrument == "MNQ JUN26"


def test_partial_block_dropped():
    bars_1h = [
        _bar(BASE_1700_CT + h * 3600, 100, 110, 90, 105, 1000)
        for h in range(3)
    ]
    assert derive_4h(bars_1h) == []


def test_multiple_complete_blocks():
    bars_1h = [
        _bar(BASE_1700_CT + h * 3600, 100, 110, 90, 105, 1000)
        for h in range(8)
    ]
    out = derive_4h(bars_1h)
    assert len(out) == 2
    assert out[0].time == BASE_1700_CT
    assert out[1].time == BASE_1700_CT + 4 * 3600


def test_gap_in_middle_drops_straddling_block():
    bars_1h = [
        _bar(BASE_1700_CT + 0 * 3600, 100, 110, 90, 105, 1000),
        _bar(BASE_1700_CT + 1 * 3600, 100, 110, 90, 105, 1000),
        _bar(BASE_1700_CT + 2 * 3600, 100, 110, 90, 105, 1000),
        _bar(BASE_1700_CT + 4 * 3600, 100, 110, 90, 105, 1000),
    ]
    assert derive_4h(bars_1h) == []


def test_13_to_17_ct_block_spanning_daily_break_not_emitted():
    base_1300_ct = BASE_1700_CT - 4 * 3600
    bars_1h = [
        _bar(base_1300_ct + h * 3600, 100, 110, 90, 105, 1000)
        for h in range(3)
    ]
    assert derive_4h(bars_1h) == []
