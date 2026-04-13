from db import connect
from models.bar import Bar
from services.ohlc.store import insert_many, list_times, read_range


def _bar(t: int, *, close: float = 100.0, src: str = "yfinance") -> Bar:
    return Bar(
        instrument="MNQ",
        timeframe="1m",
        time=t,
        open=close - 0.25,
        high=close + 0.50,
        low=close - 0.50,
        close=close,
        volume=10,
        source=src,
    )


def test_insert_many_then_read_range(migrated_db):
    conn = connect(migrated_db)
    try:
        insert_many(conn, [_bar(60), _bar(120), _bar(180)])
        bars = read_range(conn, instrument="MNQ", timeframe="1m", start=0, end=1000)
    finally:
        conn.close()
    assert [b.time for b in bars] == [60, 120, 180]
    assert all(isinstance(b, Bar) for b in bars)


def test_insert_many_empty_is_noop(migrated_db):
    conn = connect(migrated_db)
    try:
        insert_many(conn, [])
        assert read_range(conn, instrument="MNQ", timeframe="1m", start=0, end=1000) == []
    finally:
        conn.close()


def test_insert_many_upserts_on_conflict(migrated_db):
    conn = connect(migrated_db)
    try:
        insert_many(conn, [_bar(60, close=100.0, src="yfinance")])
        insert_many(conn, [_bar(60, close=200.0, src="stooq")])
        bars = read_range(conn, instrument="MNQ", timeframe="1m", start=0, end=1000)
    finally:
        conn.close()
    assert len(bars) == 1
    assert bars[0].close == 200.0
    assert bars[0].source == "stooq"


def test_read_range_excludes_end(migrated_db):
    conn = connect(migrated_db)
    try:
        insert_many(conn, [_bar(60), _bar(120), _bar(180)])
        bars = read_range(conn, instrument="MNQ", timeframe="1m", start=60, end=180)
    finally:
        conn.close()
    assert [b.time for b in bars] == [60, 120]


def test_read_range_filters_by_timeframe(migrated_db):
    conn = connect(migrated_db)
    try:
        b1 = _bar(60)
        b5 = _bar(60).model_copy(update={"timeframe": "5m"})
        insert_many(conn, [b1, b5])
        bars_1m = read_range(conn, instrument="MNQ", timeframe="1m", start=0, end=1000)
        bars_5m = read_range(conn, instrument="MNQ", timeframe="5m", start=0, end=1000)
    finally:
        conn.close()
    assert [b.timeframe for b in bars_1m] == ["1m"]
    assert [b.timeframe for b in bars_5m] == ["5m"]


def test_list_times_returns_sorted_unix_ts(migrated_db):
    conn = connect(migrated_db)
    try:
        insert_many(conn, [_bar(120), _bar(60), _bar(180)])
        times = list_times(conn, instrument="MNQ", timeframe="1m", start=0, end=1000)
    finally:
        conn.close()
    assert times == [60, 120, 180]
