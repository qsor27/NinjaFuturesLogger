from datetime import date

from db import connect
from models.execution import Execution
from models.statistics import StatsFilter
from services.import_db import bulk_insert_executions
from services.statistics import StatisticsService


def _seed(db_path, *, account="Sim", instrument="MNQ"):
    """Seed one closed Long position on session 2026-04-13 (Chicago)."""
    conn = connect(db_path)
    try:
        bulk_insert_executions(
            conn,
            [
                Execution(
                    nt_execution_id="a",
                    account=account,
                    instrument=instrument,
                    timestamp=1776070800,  # 2026-04-13 09:00 UTC = 04:00 CDT
                    side="Buy",
                    original_action="Buy",
                    quantity=1,
                    price=100.0,
                    commission=2.0,
                    entry_exit="Entry",
                    position_after="1 L",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=1,
                ),
                Execution(
                    nt_execution_id="b",
                    account=account,
                    instrument=instrument,
                    timestamp=1776071400,  # 2026-04-13 09:10 UTC
                    side="Sell",
                    original_action="Sell",
                    quantity=1,
                    price=110.0,
                    commission=2.0,
                    entry_exit="Exit",
                    position_after="-",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=2,
                ),
            ],
        )
    finally:
        conn.close()


def _seed_extra_account(db_path):
    conn = connect(db_path)
    try:
        bulk_insert_executions(
            conn,
            [
                Execution(
                    nt_execution_id="c",
                    account="B",
                    instrument="MNQ",
                    timestamp=1776070800,
                    side="Buy",
                    original_action="Buy",
                    quantity=1,
                    price=100.0,
                    commission=2.0,
                    entry_exit="Entry",
                    position_after="1 L",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=1,
                ),
                Execution(
                    nt_execution_id="d",
                    account="B",
                    instrument="MNQ",
                    timestamp=1776071400,
                    side="Sell",
                    original_action="Sell",
                    quantity=1,
                    price=110.0,
                    commission=2.0,
                    entry_exit="Exit",
                    position_after="-",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=2,
                ),
            ],
        )
    finally:
        conn.close()


def _service(db_path) -> StatisticsService:
    from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig

    cfg = Config(
        data_dir="data",
        db_path=str(db_path),
        inbox_dir="data/inbox",
        archive_dir="data/archive",
        log_dir="data/logs",
        session=SessionConfig(
            exchange_timezone="America/Chicago",
            trade_date_rollover="16:00",
            archive_job_time="18:00",
        ),
        thread_pool=ThreadPoolConfig(max_workers=2),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
    )
    return StatisticsService(cfg)


def test_load_closed_positions_buckets(migrated_db):
    db_path = migrated_db
    _seed(db_path)
    svc = _service(db_path)
    result = svc._load_closed_positions(StatsFilter())
    assert len(result.closed_with_pnl) == 1
    assert len(result.closed_missing_multiplier) == 0
    assert len(result.open) == 0
    assert result.closed_with_pnl[0].dollars_pnl is not None


def test_load_closed_positions_filters_by_account(migrated_db):
    db_path = migrated_db
    _seed(db_path, account="A")
    _seed_extra_account(db_path)
    svc = _service(db_path)
    result_a = svc._load_closed_positions(StatsFilter(accounts=("A",)))
    result_b = svc._load_closed_positions(StatsFilter(accounts=("B",)))
    assert len(result_a.closed_with_pnl) == 1
    assert len(result_b.closed_with_pnl) == 1
    assert result_a.closed_with_pnl[0].account == "A"
    assert result_b.closed_with_pnl[0].account == "B"


def test_load_closed_positions_filters_by_multiple_accounts(migrated_db):
    db_path = migrated_db
    _seed(db_path, account="A")
    _seed_extra_account(db_path)
    svc = _service(db_path)
    # Empty tuple = all accounts
    result_all = svc._load_closed_positions(StatsFilter())
    assert len(result_all.closed_with_pnl) == 2
    # Multi-account filter returns the union
    result_ab = svc._load_closed_positions(StatsFilter(accounts=("A", "B")))
    assert len(result_ab.closed_with_pnl) == 2
    returned = sorted(p.account for p in result_ab.closed_with_pnl)
    assert returned == ["A", "B"]
    # Single-element tuple still works
    result_a = svc._load_closed_positions(StatsFilter(accounts=("A",)))
    assert len(result_a.closed_with_pnl) == 1


def test_load_closed_positions_filters_by_session_date_range(migrated_db):
    db_path = migrated_db
    _seed(db_path)  # session date 2026-04-13
    svc = _service(db_path)
    in_range = svc._load_closed_positions(
        StatsFilter(from_date=date(2026, 4, 13), to_date=date(2026, 4, 13))
    )
    out_of_range = svc._load_closed_positions(
        StatsFilter(from_date=date(2026, 4, 14), to_date=date(2026, 4, 30))
    )
    assert len(in_range.closed_with_pnl) == 1
    assert len(out_of_range.closed_with_pnl) == 0


def _fresh(migrated_db):
    _seed(migrated_db)
    return migrated_db


def test_summary_returns_typed_response(migrated_db):
    svc = _service(_fresh(migrated_db))
    s = svc.summary(StatsFilter())
    assert s.total_positions == 1
    assert s.wins == 1
    assert s.losses == 0
    assert s.win_rate == 1.0
    assert s.open_positions == 0
    assert s.skipped_no_multiplier == 0


def test_by_instrument(migrated_db):
    svc = _service(_fresh(migrated_db))
    r = svc.by_instrument(StatsFilter())
    assert len(r.rows) == 1
    assert r.rows[0].instrument == "MNQ"


def test_by_day(migrated_db):
    svc = _service(_fresh(migrated_db))
    r = svc.by_day(StatsFilter())
    assert r.granularity == "day"
    assert any(b.position_count == 1 for b in r.buckets)


def test_by_week(migrated_db):
    svc = _service(_fresh(migrated_db))
    r = svc.by_week(StatsFilter())
    assert r.granularity == "week"
    assert any(b.bucket.startswith("2026-W") for b in r.buckets)


def test_by_month(migrated_db):
    svc = _service(_fresh(migrated_db))
    r = svc.by_month(StatsFilter())
    assert r.granularity == "month"
    assert any(b.bucket == "2026-04" for b in r.buckets)


def test_by_hour_uses_display_timezone_default(migrated_db):
    svc = _service(_fresh(migrated_db))
    r = svc.by_hour(StatsFilter())
    assert r.timezone == "America/Chicago"
    assert len(r.buckets) == 24
    assert sum(b.position_count for b in r.buckets) == 1


def test_by_hour_honors_display_timezone_override(migrated_db):
    db_path = _fresh(migrated_db)
    from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig

    cfg = Config(
        data_dir="data",
        db_path=str(db_path),
        inbox_dir="data/inbox",
        archive_dir="data/archive",
        log_dir="data/logs",
        session=SessionConfig(
            exchange_timezone="America/Chicago",
            trade_date_rollover="16:00",
            archive_job_time="18:00",
        ),
        thread_pool=ThreadPoolConfig(max_workers=2),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
        display_timezone="Asia/Tokyo",
    )
    svc = StatisticsService(cfg)
    r = svc.by_hour(StatsFilter())
    assert r.timezone == "Asia/Tokyo"


def test_by_side(migrated_db):
    svc = _service(_fresh(migrated_db))
    r = svc.by_side(StatsFilter())
    assert r.long.position_count == 1
    assert r.short.position_count == 0


def test_equity_curve(migrated_db):
    svc = _service(_fresh(migrated_db))
    r = svc.equity_curve(StatsFilter())
    assert len(r.series) == 1
    assert r.series[0].account == "Sim"
    assert len(r.series[0].points) == 1
    assert r.series[0].points[0].cumulative_pnl > 0


def test_equity_curve_multi_account(migrated_db):
    db_path = migrated_db
    _seed(db_path, account="A")
    _seed_extra_account(db_path)
    svc = _service(db_path)
    r = svc.equity_curve(StatsFilter())
    accounts = sorted(s.account for s in r.series)
    assert accounts == ["A", "B"]
    for s in r.series:
        assert len(s.points) == 1
        assert s.points[0].cumulative_pnl > 0


def test_distribution(migrated_db):
    svc = _service(_fresh(migrated_db))
    r = svc.distribution(StatsFilter())
    assert r.bucket_count == 10
    assert len(r.buckets) == 10


def test_by_day_of_week(migrated_db):
    # Seeded position is on 2026-04-13 = Monday (dow 0)
    svc = _service(_fresh(migrated_db))
    r = svc.by_day_of_week(StatsFilter())
    assert len(r.buckets) == 5
    assert r.buckets[0].day_name == "Mon"
    assert r.buckets[0].trades == 1
    assert r.buckets[0].trading_days == 1
    # Other days have zero trades
    assert all(b.trades == 0 for b in r.buckets[1:])


def test_by_hour_display_tz_override(migrated_db):
    # Seed: entry_time 1776070800 = 2026-04-13 09:00 UTC
    #   → hour 4 in America/Chicago (default)
    #   → hour 5 in America/New_York
    svc = _service(_fresh(migrated_db))
    r_default = svc.by_hour(StatsFilter())
    assert r_default.timezone == "America/Chicago"
    assert r_default.buckets[4].position_count == 1

    r_ny = svc.by_hour(StatsFilter(), display_tz_override="America/New_York")
    assert r_ny.timezone == "America/New_York"
    assert r_ny.buckets[5].position_count == 1
    assert r_ny.buckets[4].position_count == 0


def test_by_hour_invalid_tz_falls_back_to_default(migrated_db):
    svc = _service(_fresh(migrated_db))
    r = svc.by_hour(StatsFilter(), display_tz_override="Not/A_RealZone")
    assert r.timezone == "America/Chicago"
    assert r.buckets[4].position_count == 1


def test_by_hour_has_win_rate_field(migrated_db):
    # The single seeded position is a winner (+$10 × multiplier, 0 commission)
    svc = _service(_fresh(migrated_db))
    r = svc.by_hour(StatsFilter())
    assert r.buckets[4].win_rate == 1.0
    # Hours with no trades have None
    assert r.buckets[0].win_rate is None


def test_by_trades_per_day(migrated_db):
    # Seeded: one session date (2026-04-13) with exactly 1 trade
    svc = _service(_fresh(migrated_db))
    r = svc.by_trades_per_day(StatsFilter())
    assert len(r.buckets) == 1
    b = r.buckets[0]
    assert b.trades_per_day == 1
    assert b.days == 1
    assert b.total_trades == 1
    assert b.wins == 1
    assert b.win_rate == 1.0
