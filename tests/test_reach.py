from services.ohlc.reach import PROVIDER_REACH, reach_floor


def test_provider_reach_table_has_all_intraday_timeframes():
    for tf in ("1m", "5m", "15m", "1h", "1d", "1wk", "1mo"):
        assert tf in PROVIDER_REACH


def test_1m_reach_is_30_days():
    assert PROVIDER_REACH["1m"] == 30 * 86400


def test_5m_and_15m_reach_is_60_days():
    assert PROVIDER_REACH["5m"] == 60 * 86400
    assert PROVIDER_REACH["15m"] == 60 * 86400


def test_1h_reach_is_730_days():
    assert PROVIDER_REACH["1h"] == 730 * 86400


def test_1d_reach_is_effectively_unlimited():
    assert PROVIDER_REACH["1d"] >= 30 * 365 * 86400


def test_reach_floor_intraday_returns_now_minus_reach():
    now = 1_776_254_400
    assert reach_floor("1m", now=now) == now - 30 * 86400
    assert reach_floor("5m", now=now) == now - 60 * 86400
    assert reach_floor("15m", now=now) == now - 60 * 86400


def test_reach_floor_margin_moves_floor_forward():
    now = 1_776_254_400
    assert reach_floor("1m", now=now, margin=3600) == now - 30 * 86400 + 3600


def test_reach_floor_unlimited_for_1h_and_daily_and_above():
    now = 1_776_254_400
    for tf in ("1h", "1d", "1wk", "1mo"):
        assert reach_floor(tf, now=now) is None


def test_reach_floor_unknown_timeframe_is_unlimited():
    assert reach_floor("4h", now=1_776_254_400) is None


def test_gap_reports_never_record_what_the_fetcher_drops(tmp_path):
    """B1 cross-site pin: a gap inside raw provider reach but within the
    fetcher's safety margin is dropped by _clamp_gaps_to_reach, so
    update_gap_reports must not record it as a fillable gap either."""
    from pathlib import Path

    from db import connect
    from migrations import run_migrations
    from services.ohlc.fetcher import _clamp_gaps_to_reach
    from services.ohlc.gap_reports import update_gap_reports

    now = 1_776_254_400  # Wed 2026-04-15 12:00 UTC
    # 30 min inside the raw 1m reach boundary, but within the 3600s margin.
    # 2026-03-16 ~12:30 UTC — Monday ~07:30 CT — in-session, no daily break.
    gap_end = (now - 30 * 86400) + 1800
    gap_start = gap_end - 600

    clamped, dropped = _clamp_gaps_to_reach([(gap_start, gap_end)], timeframe="1m", now=now)
    assert clamped == [] and dropped == 1

    conn = connect(tmp_path / "t.db")
    try:
        run_migrations(conn, Path("migrations"))
        update_gap_reports(
            conn,
            instrument="MNQ",
            timeframe="1m",
            range_start=gap_start,
            range_end=gap_end,
            attempt_id=None,
            now=now,
        )
        rows = conn.execute("SELECT * FROM ohlc_gap_reports WHERE state = 'open'").fetchall()
    finally:
        conn.close()
    assert rows == []
