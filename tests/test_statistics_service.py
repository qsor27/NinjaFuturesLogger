from datetime import date
from pathlib import Path

from db import connect
from migrations import run_migrations
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


def _migrated_db(tmp_path) -> Path:
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    try:
        run_migrations(conn, Path("migrations"))
    finally:
        conn.close()
    return db_path


def test_load_closed_positions_buckets(tmp_path):
    db_path = _migrated_db(tmp_path)
    _seed(db_path)
    svc = _service(db_path)
    result = svc._load_closed_positions(StatsFilter())
    assert len(result.closed_with_pnl) == 1
    assert len(result.closed_missing_multiplier) == 0
    assert len(result.open) == 0
    assert result.closed_with_pnl[0].dollars_pnl is not None


def test_load_closed_positions_filters_by_account(tmp_path):
    db_path = _migrated_db(tmp_path)
    _seed(db_path, account="A")
    _seed_extra_account(db_path)
    svc = _service(db_path)
    result_a = svc._load_closed_positions(StatsFilter(account="A"))
    result_b = svc._load_closed_positions(StatsFilter(account="B"))
    assert len(result_a.closed_with_pnl) == 1
    assert len(result_b.closed_with_pnl) == 1
    assert result_a.closed_with_pnl[0].account == "A"
    assert result_b.closed_with_pnl[0].account == "B"


def test_load_closed_positions_filters_by_session_date_range(tmp_path):
    db_path = _migrated_db(tmp_path)
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


def _fresh(tmp_path):
    db_path = _migrated_db(tmp_path)
    _seed(db_path)
    return db_path


def test_summary_returns_typed_response(tmp_path):
    svc = _service(_fresh(tmp_path))
    s = svc.summary(StatsFilter())
    assert s.total_positions == 1
    assert s.wins == 1
    assert s.losses == 0
    assert s.win_rate == 1.0
    assert s.open_positions == 0
    assert s.skipped_no_multiplier == 0


def test_by_instrument(tmp_path):
    svc = _service(_fresh(tmp_path))
    r = svc.by_instrument(StatsFilter())
    assert len(r.rows) == 1
    assert r.rows[0].instrument == "MNQ"


def test_by_day(tmp_path):
    svc = _service(_fresh(tmp_path))
    r = svc.by_day(StatsFilter())
    assert r.granularity == "day"
    assert any(b.position_count == 1 for b in r.buckets)


def test_by_week(tmp_path):
    svc = _service(_fresh(tmp_path))
    r = svc.by_week(StatsFilter())
    assert r.granularity == "week"
    assert any(b.bucket.startswith("2026-W") for b in r.buckets)


def test_by_month(tmp_path):
    svc = _service(_fresh(tmp_path))
    r = svc.by_month(StatsFilter())
    assert r.granularity == "month"
    assert any(b.bucket == "2026-04" for b in r.buckets)


def test_by_hour_uses_display_timezone_default(tmp_path):
    svc = _service(_fresh(tmp_path))
    r = svc.by_hour(StatsFilter())
    assert r.timezone == "America/Chicago"
    assert len(r.buckets) == 24
    assert sum(b.position_count for b in r.buckets) == 1


def test_by_hour_honors_display_timezone_override(tmp_path):
    db_path = _fresh(tmp_path)
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


def test_by_side(tmp_path):
    svc = _service(_fresh(tmp_path))
    r = svc.by_side(StatsFilter())
    assert r.long.position_count == 1
    assert r.short.position_count == 0


def test_equity_curve(tmp_path):
    svc = _service(_fresh(tmp_path))
    r = svc.equity_curve(StatsFilter())
    assert len(r.points) == 1
    assert r.points[0].cumulative_pnl > 0


def test_distribution(tmp_path):
    svc = _service(_fresh(tmp_path))
    r = svc.distribution(StatsFilter())
    assert r.bucket_count == 10
    assert len(r.buckets) == 10
