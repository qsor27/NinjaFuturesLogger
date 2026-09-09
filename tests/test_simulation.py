from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from models.simulation import SimulationRule
from models.statistics import StatsFilter
from services.simulation import max_drawdown, run_simulation
from tests.conftest import make_position

T0 = 1776088800  # Mon 2026-04-13 09:00 CDT
DAY = 86400
WEEK = 7 * DAY
CT = ZoneInfo("America/Chicago")


def _pos(i, pnl, entry, exit=None, **over):
    return make_position(
        entry_execution_id=f"e{i}",
        entry_time=entry,
        exit_time=exit if exit is not None else entry + 60,
        dollars_pnl=pnl,
        commission=0.5,
        execution_ids=[f"e{i}"],
        **over,
    )


def _seq(pnls, start=T0, step=600):
    """Non-overlapping trades: entry every `step` seconds, each lasting 60s."""
    return [_pos(i, pnl, start + i * step) for i, pnl in enumerate(pnls)]


def _rule(**over):
    base = dict(
        metric="losses", scope="session", comparator=">=", threshold=2, action="stop_session"
    )
    base.update(over)
    return SimulationRule(**base)


def _run(positions, rules, tz=CT):
    return run_simulation(positions, rules, display_tz=tz, filter=StatsFilter())


def _skipped_ids(result):
    return [s.entry_execution_id for s in result.skipped]


def test_zero_rules_is_identity():
    ps = _seq([-10, 20, -5, 7])
    r = _run(ps, [])
    assert r.simulated == r.actual
    assert r.skipped == []
    assert r.rule_attribution == []
    assert r.by_day == []
    assert r.inputs.positions_considered == 4


def test_two_losses_stop_session():
    ps = _seq([-10, -10, 50, -10])
    r = _run(ps, [_rule()])
    assert _skipped_ids(r) == ["e2", "e3"]
    assert r.actual.summary.total_pnl == 20
    assert r.simulated.summary.total_pnl == -20
    assert r.delta.total_pnl == -40
    assert r.skipped_summary.count == 2
    assert r.skipped_summary.winners == 1 and r.skipped_summary.winners_pnl == 50
    assert r.skipped_summary.losers == 1 and r.skipped_summary.losers_pnl == -10
    att = r.rule_attribution[0]
    assert (att.fires, att.skipped_trades, att.skipped_pnl) == (1, 2, 40)
    assert att.label == "losses in session >= 2 -> stop for session"


def test_skipped_trades_do_not_feed_counters():
    ps = _seq([-10, -10, -10, -10])
    rules = [_rule(), _rule(threshold=3, action="stop_week")]
    r = _run(ps, rules)
    assert _skipped_ids(r) == ["e2", "e3"]
    assert r.rule_attribution[1].fires == 0


def test_session_scope_resets_next_day():
    day1 = _seq([-10, -10, 30])
    day2 = _seq([-10, 40], start=T0 + DAY)
    for i, p in enumerate(day2):
        day2[i] = p.model_copy(update={"entry_execution_id": f"d{i}", "execution_ids": [f"d{i}"]})
    r = _run(day1 + day2, [_rule()])
    assert _skipped_ids(r) == ["e2"]
    assert r.simulated.summary.total_pnl == -10 - 10 - 10 + 40


def test_session_rollover_at_1600_chicago():
    # 15:50 CDT and 16:10 CDT are different sessions.
    before = T0 + 6 * 3600 + 50 * 60  # 15:50 CDT
    after = T0 + 7 * 3600 + 10 * 60  # 16:10 CDT
    ps = [_pos(0, -10, before), _pos(1, -10, before + 120), _pos(2, 5, after)]
    r = _run(ps, [_rule()])
    assert _skipped_ids(r) == []  # halt cleared by the rollover
    assert r.rule_attribution[0].fires == 1


def test_zero_duration_position_feeds_counters():
    ps = [_pos(0, -10, T0, T0), _pos(1, -10, T0 + 600, T0 + 600), _pos(2, 5, T0 + 1200)]
    r = _run(ps, [_rule()])  # losses >= 2 -> stop session
    assert _skipped_ids(r) == ["e2"]
    assert r.rule_attribution[0].fires == 1
    assert r.simulated.summary.total_positions == 2


def test_trades_count_metric():
    r = _run(_seq([1, 1, 1]), [_rule(metric="trades")])
    assert _skipped_ids(r) == ["e2"]


def test_wins_count_metric():
    r = _run(_seq([5, 5, 5, -1]), [_rule(metric="wins", threshold=2)])
    assert _skipped_ids(r) == ["e2", "e3"]


def test_scratches_count_metric():
    # commission is 0.5 so |pnl| <= 0.5 is a scratch
    r = _run(_seq([0.0, 0.3, 9]), [_rule(metric="scratches", threshold=2)])
    assert _skipped_ids(r) == ["e2"]


def test_open_position_rejected():
    p = make_position(exit_time=None, dollars_pnl=None)
    with pytest.raises(ValueError):
        _run([p], [])


def test_max_drawdown_known_sequence():
    ps = _seq([10, -5, -10, 20, -30])  # cum: 10, 5, -5, 15, -15 -> worst 30
    assert max_drawdown(ps) == 30
    assert max_drawdown([]) == 0.0
    assert max_drawdown(_seq([5, 5])) == 0.0


def test_result_blocks_carry_drawdown_and_equity():
    ps = _seq([10, -5, -10, 20, -30])
    r = _run(ps, [_rule(metric="losses", threshold=1)])
    assert r.actual.max_drawdown == 30
    assert _skipped_ids(r) == ["e2", "e3", "e4"]
    assert r.simulated.max_drawdown == 5
    assert r.delta.max_drawdown == -25
    assert len(r.actual.equity) == 1  # one session date
    assert r.actual.equity[0].cumulative_pnl == -15
    assert r.simulated.equity[0].cumulative_pnl == 5


def test_by_day_rows_only_for_days_with_skips():
    day1 = _seq([-10, -10, 30])
    day2 = [_pos(9, 40, T0 + DAY)]
    r = _run(day1 + day2, [_rule()])
    assert [row.session_date for row in r.by_day] == [date(2026, 4, 13)]
    row = r.by_day[0]
    assert (row.actual_pnl, row.simulated_pnl, row.skipped_count, row.rules_fired) == (
        10,
        -20,
        1,
        [0],
    )


def test_inputs_echo_filter_and_tz():
    f = StatsFilter(accounts=("A",), from_date=date(2026, 4, 1), side="Long")
    r = run_simulation(_seq([1]), [_rule()], display_tz=CT, filter=f)
    assert r.inputs.accounts == ("A",)
    assert r.inputs.from_date == date(2026, 4, 1)
    assert r.inputs.side == "Long"
    assert r.inputs.display_tz == "America/Chicago"
    assert r.inputs.rules[0].label.startswith("losses in session")


def test_scratch_resets_loss_streak():
    rule = _rule(metric="consecutive_losses")
    no_fire = _run(_seq([-10, 0.0, -10, 20]), [rule])
    assert _skipped_ids(no_fire) == []
    fire = _run(_seq([-10, -10, 20]), [rule])
    assert _skipped_ids(fire) == ["e2"]


def test_consecutive_wins():
    r = _run(_seq([10, 10, 10, 10, -5]), [_rule(metric="consecutive_wins", threshold=3)])
    assert _skipped_ids(r) == ["e3", "e4"]


def test_net_pnl_floor():
    r = _run(_seq([-10, -10, 50]), [_rule(metric="net_pnl", comparator="<=", threshold=-15)])
    assert _skipped_ids(r) == ["e2"]


def test_net_pnl_ceiling_locks_in_gains():
    r = _run(_seq([30, 30, -50]), [_rule(metric="net_pnl", threshold=50)])
    assert _skipped_ids(r) == ["e2"]
    assert r.simulated.summary.total_pnl == 60


def test_drawdown_from_scope_peak():
    ps = _seq([50, -20, -15, 10])  # net: 50, 30, 15 -> dd 35 after e2
    dd = _run(ps, [_rule(metric="drawdown", threshold=30)])
    assert _skipped_ids(dd) == ["e3"]
    floor = _run(ps, [_rule(metric="net_pnl", comparator="<=", threshold=-30)])
    assert _skipped_ids(floor) == []  # net never negative; drawdown is the distinct signal


def test_week_scope_and_stop_week():
    d1 = [_pos(0, -10, T0)]
    d2 = [_pos(1, -10, T0 + DAY), _pos(2, 5, T0 + DAY + 600)]
    d3 = [_pos(3, 5, T0 + 2 * DAY)]
    next_week = [_pos(4, 7, T0 + WEEK)]
    r = _run(d1 + d2 + d3 + next_week, [_rule(scope="week", action="stop_week")])
    assert _skipped_ids(r) == ["e2", "e3"]
    assert r.simulated.summary.total_pnl == -10 - 10 + 7


def test_all_scope_carries_streak_across_days():
    ps = [_pos(0, -10, T0), _pos(1, -10, T0 + DAY), _pos(2, 5, T0 + DAY + 600)]
    across = _run(ps, [_rule(metric="consecutive_losses", scope="all")])
    assert _skipped_ids(across) == ["e2"]
    per_session = _run(ps, [_rule(metric="consecutive_losses", scope="session")])
    assert _skipped_ids(per_session) == []


def test_pause_minutes_expires():
    ps = [
        _pos(0, -10, T0),  # exits T0+60 -> pause until T0+60+1800
        _pos(1, 5, T0 + 600),  # inside the pause
        _pos(2, 5, T0 + 60 + 1800),  # exactly at expiry -> allowed
    ]
    r = _run(ps, [_rule(threshold=1, action="pause_minutes", action_param=30)])
    assert _skipped_ids(r) == ["e1"]
    assert r.skipped[0].rule_index == 0


def test_pause_survives_nothing_but_time():
    # A pause is not cleared by a session rollover; only its timestamp matters.
    late = T0 + 6 * 3600 + 55 * 60  # 15:55 CDT, exits 15:56
    ps = [_pos(0, -10, late), _pos(1, 5, late + 10 * 60)]  # 16:05 CDT, new session
    r = _run(ps, [_rule(threshold=1, action="pause_minutes", action_param=30)])
    assert _skipped_ids(r) == ["e1"]


def test_overlapping_positions_use_exit_for_outcome():
    a = _pos(0, -10, T0, T0 + 1200)
    b = _pos(1, -10, T0 + 300, T0 + 400)
    c = _pos(2, 5, T0 + 1500)
    r = _run([a, b, c], [_rule(threshold=1)])
    assert _skipped_ids(r) == ["e2"]  # b entered before any loss was known
    assert r.simulated.summary.total_pnl == -20
    assert r.rule_attribution[0].fires == 2  # b's exit and a's exit both satisfy losses >= 1


def test_time_of_day_gate_in_display_tz():
    ps = [
        _pos(0, 5, T0),  # 09:00 CDT
        _pos(1, 5, T0 + 2 * 3600),  # 11:00 CDT -> fires
        _pos(2, 5, T0 + 2 * 3600 + 1800),  # 11:30 halted
        _pos(3, 5, T0 + DAY),  # next day 09:00 -> taken
    ]
    r = _run(ps, [_rule(metric="time_of_day", threshold="11:00")])
    assert _skipped_ids(r) == ["e1", "e2"]
    assert r.rule_attribution[0].fires == 1


def test_time_of_day_across_dst_boundary():
    ny = ZoneInfo("America/New_York")
    pre = int(datetime(2026, 3, 2, 15, 30, tzinfo=UTC).timestamp())  # 10:30 EST
    post = int(datetime(2026, 3, 9, 15, 30, tzinfo=UTC).timestamp())  # 11:30 EDT
    ps = [_pos(0, 5, pre), _pos(1, 5, post)]
    r = _run(ps, [_rule(metric="time_of_day", threshold="11:00")], tz=ny)
    assert _skipped_ids(r) == ["e1"]


def test_multi_rule_same_exit_strongest_action_wins():
    rules = [
        _rule(threshold=1, action="pause_minutes", action_param=30),
        _rule(threshold=1, action="stop_session"),
    ]
    ps = [_pos(0, -10, T0), _pos(1, 5, T0 + 600), _pos(2, 5, T0 + 3 * 3600)]
    r = _run(ps, rules)
    assert _skipped_ids(r) == ["e1", "e2"]
    assert [s.rule_index for s in r.skipped] == [1, 1]
    assert [a.fires for a in r.rule_attribution] == [1, 1]
    assert [a.skipped_trades for a in r.rule_attribution] == [0, 2]


def test_multiple_accounts_share_one_stream():
    a = _pos(0, -10, T0, account="A")
    b = _pos(1, -10, T0 + 600, account="B")
    c = _pos(2, 5, T0 + 1200, account="A")
    r = _run([a, b, c], [_rule()])
    assert _skipped_ids(r) == ["e2"]
