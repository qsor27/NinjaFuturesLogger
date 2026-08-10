# tests/test_review_deck_db.py
from db import connect
from services.ohlc.store import insert_many
from services.review_deck import (
    MIN_COVERAGE_BARS,
    card_bars,
    eligible_cards,
    find_position,
    reveal_bars,
)
from tests.conftest import make_bar, make_execution, seed_executions

ENTRY_TS = 100_000  # 1666:40 -> boundary 99_960
BOUNDARY = 99_960


def _seed_round_trip(db_path, *, entry_id="e1", exit_id="x1", entry_ts=ENTRY_TS):
    """One closed long: buy 1 @ entry_ts, sell 1 @ entry_ts + 300."""
    seed_executions(
        db_path,
        [
            make_execution(
                entry_id, timestamp=entry_ts, side="Buy", entry_exit="Entry", price=100.0
            ),
            make_execution(
                exit_id,
                timestamp=entry_ts + 300,
                side="Sell",
                entry_exit="Exit",
                price=101.0,
                position_after="-",
            ),
        ],
    )


def _seed_coverage(db_path, *, count=MIN_COVERAGE_BARS, end=BOUNDARY):
    conn = connect(db_path)
    try:
        insert_many(
            conn,
            [make_bar(time=end - 60 * (i + 1)) for i in range(count)],
        )
        conn.commit()
    finally:
        conn.close()


def test_eligible_requires_closed_and_covered(migrated_db):
    _seed_round_trip(migrated_db)
    # no bars yet -> not covered
    assert eligible_cards(migrated_db) == []
    _seed_coverage(migrated_db)
    cards = eligible_cards(migrated_db)
    assert [c.entry_execution_id for c in cards] == ["e1"]
    assert cards[0].entry_time == ENTRY_TS


def test_open_position_is_never_a_card(migrated_db):
    seed_executions(
        migrated_db,
        [make_execution("e9", timestamp=ENTRY_TS, side="Buy", entry_exit="Entry")],
    )
    _seed_coverage(migrated_db)
    assert eligible_cards(migrated_db) == []


def test_under_threshold_coverage_excluded(migrated_db):
    _seed_round_trip(migrated_db)
    _seed_coverage(migrated_db, count=MIN_COVERAGE_BARS - 1)
    assert eligible_cards(migrated_db) == []


def test_find_position_returns_fills(migrated_db):
    _seed_round_trip(migrated_db)
    found = find_position(migrated_db, "e1")
    assert found is not None
    position, fills = found
    assert position.exit_time == ENTRY_TS + 300
    assert [f.entry_exit for f in fills] == ["Entry", "Exit"]
    assert find_position(migrated_db, "nope") is None


# --- the anti-leak tests (load-bearing) --------------------------------------


def test_card_bars_1m_exclude_entry_minute(migrated_db):
    conn = connect(migrated_db)
    try:
        insert_many(
            conn,
            [make_bar(time=t) for t in (BOUNDARY - 120, BOUNDARY - 60, BOUNDARY, BOUNDARY + 60)],
        )
        conn.commit()
        bars = card_bars(conn, instrument="MNQ", timeframe="1m", entry_ts=ENTRY_TS)
        assert [b.time for b in bars] == [BOUNDARY - 120, BOUNDARY - 60]
    finally:
        conn.close()


def test_card_bars_5m_completed_plus_partial(migrated_db):
    # BOUNDARY = 99_960; 5m bucket = 99_900..100_200 -> one completed 1m bar
    # (99_900) forms the partial; completed 5m bars end at 99_900 exclusive.
    conn = connect(migrated_db)
    try:
        insert_many(
            conn,
            [
                make_bar(timeframe="5m", time=99_300),
                make_bar(timeframe="5m", time=99_600),
                make_bar(timeframe="5m", time=99_900, high=999.0),  # in-progress at entry: leak
                make_bar(timeframe="1m", time=99_900, high=101.0),
                make_bar(timeframe="1m", time=99_960, high=888.0),  # entry minute: leak
            ],
        )
        conn.commit()
        bars = card_bars(conn, instrument="MNQ", timeframe="5m", entry_ts=ENTRY_TS)
        assert [b.time for b in bars] == [99_300, 99_600, 99_900]
        assert bars[-1].source == "derived"
        assert bars[-1].high == 101.0  # from the 1m bar, not the stored 5m bar
        for b in bars:
            assert b.high < 888.0
    finally:
        conn.close()


def test_reveal_bars_full_window(migrated_db):
    exit_time = ENTRY_TS + 300
    conn = connect(migrated_db)
    try:
        insert_many(
            conn, [make_bar(time=t) for t in range(BOUNDARY - 300, exit_time + 30 * 60, 60)]
        )
        conn.commit()
        bars = reveal_bars(
            conn, instrument="MNQ", timeframe="1m", entry_ts=ENTRY_TS, exit_time=exit_time
        )
        times = [b.time for b in bars]
        assert BOUNDARY in times  # the entry minute is now visible
        assert exit_time - (exit_time % 60) in times
        assert max(times) < exit_time + 30 * 60
    finally:
        conn.close()
