import pytest

from models.position import TREND_ALIGNMENTS
from services.entry_method import classify_trend_alignment
from services.position_filters import PositionFilter, apply_filters
from services.positions import build_positions
from tests.conftest import make_execution, make_position, seed_executions

E0 = 1776070800  # 2026-04-13 session


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("GateMktNextOpen", "with_trend"),
        ("GateLmtNextOpen", "with_trend"),
        ("GateMktNextOpenCT", "counter_trend"),
        ("GateLmtNextOpenCT", "counter_trend"),
        ("Entry", "not_gated"),
        (None, "not_gated"),
        ("", "not_gated"),
    ],
)
def test_classify_trend_alignment(name, expected):
    assert classify_trend_alignment(name) == expected


def test_trend_alignments_tuple_order():
    assert TREND_ALIGNMENTS == ("with_trend", "counter_trend", "not_gated")


def test_position_trend_alignment_comes_from_the_entry_fill():
    execs = [
        make_execution("a", timestamp=1, order_name="GateLmtNextOpenCT"),
        make_execution(
            "b",
            timestamp=2,
            side="Sell",
            original_action="Sell",
            entry_exit="Exit",
            position_after="-",
            order_name="Target1",
        ),
    ]
    positions, _ = build_positions(execs)
    assert positions[0].trend_alignment == "counter_trend"
    assert positions[0].entry_method == "limit_next_open"


def test_apply_filters_trend_alignment():
    ps = [
        make_position(entry_execution_id="w", trend_alignment="with_trend"),
        make_position(entry_execution_id="c", trend_alignment="counter_trend"),
    ]
    kept = apply_filters(ps, PositionFilter(trend_alignment="counter_trend"))
    assert [p.entry_execution_id for p in kept] == ["c"]


def _pair(i, entry_name, exit_px):
    base = E0 + i * 1200
    return [
        make_execution(
            f"a{i}",
            account="Sim",
            timestamp=base,
            price=100.0,
            commission=1.0,
            order_name=entry_name,
        ),
        make_execution(
            f"b{i}",
            account="Sim",
            timestamp=base + 600,
            side="Sell",
            original_action="Sell",
            price=exit_px,
            commission=1.0,
            entry_exit="Exit",
            position_after="-",
            order_name="Target1",
        ),
    ]


@pytest.fixture
def seeded(app):
    rows = (
        _pair(0, "GateMktNextOpen", 110.0)
        + _pair(1, "GateMktNextOpenCT", 95.0)
        + _pair(2, "GateLmtNextOpenCT", 96.0)
        + _pair(3, "Entry", 105.0)
    )
    seed_executions(app.config["FTL_DB_PATH"], rows)


def test_stats_summary_filters_by_trend_alignment(client, seeded):
    body = client.get("/api/stats/summary?trend_alignment=counter_trend").get_json()
    assert body["total_positions"] == 2
    assert body["losses"] == 2


def test_by_trend_alignment_rows(client, seeded):
    resp = client.get("/api/stats/by-trend-alignment")
    assert resp.status_code == 200
    rows = resp.get_json()["rows"]
    assert [r["trend_alignment"] for r in rows] == ["with_trend", "counter_trend", "not_gated"]
    counts = {r["trend_alignment"]: r["position_count"] for r in rows}
    assert counts == {"with_trend": 1, "counter_trend": 2, "not_gated": 1}
    by = {r["trend_alignment"]: r for r in rows}
    assert by["with_trend"]["total_pnl"] > 0
    assert by["counter_trend"]["total_pnl"] < 0


def test_invalid_trend_alignment_is_400_everywhere(client, seeded):
    for url in ("/api/stats/summary?trend_alignment=bogus", "/api/positions?trend_alignment=bogus"):
        resp = client.get(url)
        assert resp.status_code == 400
        assert "trend_alignment" in resp.get_json()["error"]
    resp = client.post(
        "/api/simulations/run",
        json={"rules": [_rule()], "trend_alignment": "bogus"},
    )
    assert resp.status_code == 400
    assert "trend_alignment" in resp.get_json()["error"]


def test_positions_list_filters_trend_alignment(client, seeded):
    resp = client.get("/api/positions?trend_alignment=with_trend")
    assert resp.status_code == 200
    assert resp.get_json()["page"]["total"] == 1


def _rule():
    return dict(
        metric="losses", scope="session", comparator=">=", threshold=2, action="stop_session"
    )


def test_simulation_run_filters_trend_alignment(client, seeded):
    resp = client.post(
        "/api/simulations/run",
        json={"rules": [_rule()], "accounts": ["Sim"], "trend_alignment": "counter_trend"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["inputs"]["positions_considered"] == 2
