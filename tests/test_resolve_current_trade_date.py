from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from services.time_utils import resolve_current_trade_date

TZ = ZoneInfo("America/Chicago")


def test_before_rollover_returns_today():
    now = datetime(2026, 4, 13, 15, 59, tzinfo=TZ)
    assert resolve_current_trade_date(now).isoformat() == "2026-04-13"


def test_at_rollover_returns_next_day():
    now = datetime(2026, 4, 13, 16, 0, tzinfo=TZ)
    assert resolve_current_trade_date(now).isoformat() == "2026-04-14"


def test_after_rollover_returns_next_day():
    now = datetime(2026, 4, 13, 17, 30, tzinfo=TZ)
    assert resolve_current_trade_date(now).isoformat() == "2026-04-14"


def test_rejects_naive():
    with pytest.raises(ValueError):
        resolve_current_trade_date(datetime(2026, 4, 13, 16, 0))
