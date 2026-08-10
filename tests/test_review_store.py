import pytest

from services.review_store import (
    attempt_stats,
    create_session,
    end_session,
    has_attempt,
    record_attempt,
    session_exists,
    summary,
)
from tests.conftest import make_execution, seed_executions


@pytest.fixture
def db(migrated_db):
    seed_executions(migrated_db, [make_execution("e1"), make_execution("e2")])
    return migrated_db


def _attempt(db, sid, entry_id, call, pnl, now=100):
    return record_attempt(
        db,
        session_id=sid,
        account="Sim101",
        instrument="MNQ",
        entry_execution_id=entry_id,
        call=call,
        outcome_pnl=pnl,
        now=now,
    )


def test_session_lifecycle(db):
    sid = create_session(db, now=10)
    assert session_exists(db, sid)
    assert not session_exists(db, sid + 1)
    assert end_session(db, sid, now=20)
    assert end_session(db, sid, now=99)  # idempotent
    assert not end_session(db, sid + 1, now=20)  # unknown id


def test_record_attempt_strips_suffix_for_fk(db):
    sid = create_session(db, now=10)
    # e1#open has no executions row; the FK must land on e1
    aid = _attempt(db, sid, "e1#open", "valid", 5.0)
    assert aid == 1
    assert has_attempt(db, sid, "e1#open")
    assert not has_attempt(db, sid, "e1")  # gating is exact on the card id


def test_attempt_stats_counts_and_recency(db):
    sid = create_session(db, now=10)
    _attempt(db, sid, "e1", "valid", 1.0, now=100)
    _attempt(db, sid, "e1", "invalid", -2.0, now=200)
    _attempt(db, sid, "e2", "valid", 3.0, now=150)
    assert attempt_stats(db) == {"e1": (2, 200), "e2": (1, 150)}


def test_summary_2x2_with_scratch(db):
    sid = create_session(db, now=10)
    other = create_session(db, now=11)
    _attempt(db, sid, "e1", "valid", 10.0)
    _attempt(db, sid, "e1", "valid", -4.0)
    _attempt(db, sid, "e2", "invalid", 6.0)
    _attempt(db, sid, "e2", "invalid", 0.0)
    _attempt(db, other, "e2", "invalid", -1.0)  # different session

    s = summary(db, session_id=sid)
    assert s.attempts == 4
    assert s.valid_won.count == 1 and s.valid_won.net_pnl == 10.0
    assert s.valid_lost.count == 1 and s.valid_lost.net_pnl == -4.0
    assert s.invalid_won.count == 1 and s.invalid_won.net_pnl == 6.0
    assert s.invalid_scratch.count == 1
    assert s.invalid_lost.count == 0

    all_time = summary(db)
    assert all_time.attempts == 5
    assert all_time.invalid_lost.count == 1
