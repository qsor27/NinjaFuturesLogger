from typing import get_args

import pytest
from pydantic import ValidationError

from models.simulation import (
    ACTIONS,
    COMPARATORS,
    MAX_RULES,
    METRICS,
    SCOPES,
    SimulationDefinitionInput,
    SimulationRule,
    rule_label,
    vocabulary,
)


def _rule(**over):
    base = dict(
        metric="losses", scope="session", comparator=">=", threshold=2, action="stop_session"
    )
    base.update(over)
    return SimulationRule(**base)


def test_count_rule_gets_server_label():
    r = _rule()
    assert r.label == "losses in session >= 2 -> stop for session"


def test_client_supplied_label_is_overwritten():
    r = _rule(label="whatever")
    assert r.label == "losses in session >= 2 -> stop for session"


def test_dollar_threshold_coerced_to_float_and_labelled():
    r = _rule(metric="net_pnl", comparator="<=", threshold=-500)
    assert r.threshold == -500.0 and isinstance(r.threshold, float)
    assert r.label == "net P&L in session <= -$500 -> stop for session"


def test_pause_label_includes_minutes():
    r = _rule(action="pause_minutes", action_param=30)
    assert r.label == "losses in session >= 2 -> pause 30 min"


def test_time_of_day_label_omits_scope():
    r = _rule(metric="time_of_day", threshold="11:00")
    assert r.label == "entry time >= 11:00 -> stop for session"


@pytest.mark.parametrize(
    "over",
    [
        dict(metric="nope"),
        dict(threshold=2.5),  # count metric needs int
        dict(threshold="2"),  # count metric rejects str
        dict(threshold=-1),  # count metric non-negative
        dict(threshold=True),  # bool is not a count
        dict(metric="net_pnl", threshold="500"),
        dict(metric="time_of_day", threshold="25:00"),
        dict(metric="time_of_day", threshold="9:00"),
        dict(metric="time_of_day", threshold=11),
        dict(metric="time_of_day", threshold="11:00", scope="week"),
        dict(action="pause_minutes"),  # missing param
        dict(action="pause_minutes", action_param=0),
        dict(action="pause_minutes", action_param=1441),
        dict(action="stop_session", action_param=5),  # param not allowed
        dict(comparator="=="),
        dict(scope="month"),
    ],
)
def test_invalid_rules_rejected(over):
    with pytest.raises(ValidationError):
        _rule(**over)


def test_definition_input_bounds():
    good = SimulationDefinitionInput(name="  Plan A ", rules=[_rule()])
    assert good.name == "Plan A"
    with pytest.raises(ValidationError):
        SimulationDefinitionInput(name="   ", rules=[_rule()])
    with pytest.raises(ValidationError):
        SimulationDefinitionInput(name="x" * 81, rules=[_rule()])
    with pytest.raises(ValidationError):
        SimulationDefinitionInput(name="x", rules=[])
    with pytest.raises(ValidationError):
        SimulationDefinitionInput(name="x", rules=[_rule()] * (MAX_RULES + 1))


def test_vocabulary_matches_enums():
    v = vocabulary()
    assert [m["value"] for m in v["metrics"]] == list(METRICS)
    assert [s["value"] for s in v["scopes"]] == list(SCOPES)
    assert [c["value"] for c in v["comparators"]] == list(COMPARATORS)
    assert [a["value"] for a in v["actions"]] == list(ACTIONS)
    assert v["max_rules"] == MAX_RULES
    types = {m["value"]: m["threshold_type"] for m in v["metrics"]}
    assert types["losses"] == "count"
    assert types["net_pnl"] == "dollars"
    assert types["time_of_day"] == "time"
    tod = next(m for m in v["metrics"] if m["value"] == "time_of_day")
    assert tod["scopes"] == ["session"]
    pause = next(a for a in v["actions"] if a["value"] == "pause_minutes")
    assert pause["needs_param"] is True
    # Every metric label is non-empty and every enum literal is covered.
    from models.simulation import Action, Comparator, Metric, Scope

    assert set(METRICS) == set(get_args(Metric))
    assert set(SCOPES) == set(get_args(Scope))
    assert set(COMPARATORS) == set(get_args(Comparator))
    assert set(ACTIONS) == set(get_args(Action))


def test_rule_label_is_pure_function():
    r = _rule(metric="drawdown", scope="week", threshold=250)
    assert rule_label(r) == "drawdown in week >= $250 -> stop for session"
