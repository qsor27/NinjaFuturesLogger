from datetime import UTC, datetime

from services.instruments import front_month_window


def _dt(y, m, d):
    return int(datetime(y, m, d, tzinfo=UTC).timestamp())


def test_mnq_jun26_window():
    # MNQH26 expires 3rd Fri of March 2026 = 2026-03-20
    # MNQM26 expires 3rd Fri of June 2026  = 2026-06-19
    # Window = [2026-03-20 00:00 UTC, 2026-06-20 00:00 UTC)
    w = front_month_window("MNQ JUN26")
    assert w is not None
    start, end = w
    assert start == _dt(2026, 3, 20)
    assert end == _dt(2026, 6, 20)


def test_mnq_dec25_window_crosses_year():
    # MNQU25 expires 3rd Fri of Sep 2025 = 2025-09-19
    # MNQZ25 expires 3rd Fri of Dec 2025 = 2025-12-19
    w = front_month_window("MNQ DEC25")
    start, end = w
    assert start == _dt(2025, 9, 19)
    assert end == _dt(2025, 12, 20)


def test_mnq_mar26_prev_quarter_is_prev_year():
    # MNQZ25 expires 3rd Fri of Dec 2025 = 2025-12-19
    # MNQH26 expires 3rd Fri of Mar 2026 = 2026-03-20
    w = front_month_window("MNQ MAR26")
    start, end = w
    assert start == _dt(2025, 12, 19)
    assert end == _dt(2026, 3, 21)


def test_continuous_returns_none():
    assert front_month_window("MNQ") is None


def test_non_quarterly_month_returns_none():
    # FEB is not in H/M/U/Z; helper declines rather than guess.
    assert front_month_window("MNQ FEB26") is None


def test_malformed_suffix_returns_none():
    assert front_month_window("MNQ BADX") is None
    assert front_month_window("MNQ JUN2X") is None
