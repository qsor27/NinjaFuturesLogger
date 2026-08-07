import json
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest
from flask import Flask

from app import create_app
from background import BackgroundServices
from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig
from db import connect
from migrations import run_migrations
from models.bar import Bar
from models.execution import Execution
from models.position import Position
from services.import_db import bulk_insert_executions
from services.instruments import set_registry_path
from services.ohlc.registry import SourceRegistry

# The NinjaTrader executions CSV header — must match ninjascript/ExecutionExporter.cs
# (doc 90). This column order is immutable; if it ever changes, it changes here once.
NINJA_CSV_HEADER = (
    "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
    "Commission,Rate,Account,Connection,TradeValidation\n"
)


def write_ninja_csv(path: Path, rows: Sequence[str]) -> Path:
    """Write NINJA_CSV_HEADER followed by `rows` (each already newline-terminated,
    except a deliberately truncated final row)."""
    path.write_text(NINJA_CSV_HEADER + "".join(rows), encoding="utf-8")
    return path


def wait_until(
    predicate: Callable[[], bool], *, timeout: float = 3.0, interval: float = 0.05
) -> bool:
    """Poll `predicate` until it is true or `timeout` seconds elapse."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class FakeOhlcSource:
    """Configurable stand-in for an OhlcSource. Records every fetch call."""

    def __init__(self, name="fake", *, supported=("1m",), bars=None, error=None):
        self.name = name
        self.supported_timeframes = frozenset(supported)
        self._bars = list(bars or [])
        self._error = error
        self.calls: list[tuple[str, str, int, int]] = []

    def fetch(self, instrument, timeframe, start, end):
        self.calls.append((instrument, timeframe, start, end))
        if self._error is not None:
            raise self._error
        return [b for b in self._bars if start <= b.time < end]


def make_source_registry(sources, *, clock=lambda: 0, threshold=3, cooldown=10) -> SourceRegistry:
    reg = SourceRegistry(clock=clock)
    for s in sources:
        reg.register(s, failure_threshold=threshold, base_cooldown_seconds=cooldown)
    return reg


@pytest.fixture(autouse=True)
def _reset_instrument_registry():
    """Restore the default registry path after every test so tests that
    call set_registry_path(tmp_path/…) don't leak into later tests."""
    yield
    set_registry_path(Path("data/config/instruments.json"))


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    (tmp_path / "inbox").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "config").mkdir()

    cfg = Config(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "t.db"),
        inbox_dir=str(tmp_path / "inbox"),
        archive_dir=str(tmp_path / "archive"),
        log_dir=str(tmp_path / "logs"),
        session=SessionConfig(
            exchange_timezone="America/Chicago",
            trade_date_rollover="16:00",
            archive_job_time="18:00",
        ),
        thread_pool=ThreadPoolConfig(max_workers=2),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
    )

    # Write the app.json file so save_filter_default can update it
    app_json = tmp_path / "config" / "app.json"
    app_json.write_text(json.dumps(cfg.model_dump()), encoding="utf-8")

    return cfg


@pytest.fixture
def migrated_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    try:
        run_migrations(conn, Path("migrations"))
    finally:
        conn.close()
    return db_path


@pytest.fixture
def app_and_services(tmp_config: Config) -> Iterator[tuple[Flask, BackgroundServices]]:
    """The real app with background work disabled. Always stopped, even on failure."""
    flask_app, services = create_app(tmp_config, start_background=False)
    try:
        yield flask_app, services
    finally:
        services.stop()


@pytest.fixture
def started_app_and_services(tmp_config: Config) -> Iterator[tuple[Flask, BackgroundServices]]:
    """The real app with scheduler + watchdog actually running."""
    flask_app, services = create_app(tmp_config, start_background=True)
    try:
        yield flask_app, services
    finally:
        services.stop()


@pytest.fixture
def app(app_and_services) -> Flask:
    return app_and_services[0]


@pytest.fixture
def client(app):
    return app.test_client()


def make_execution(eid: str = "e", **overrides) -> Execution:
    """Build an Execution with sane defaults; override any field by keyword."""
    base = dict(
        nt_execution_id=eid,
        account="Sim101",
        instrument="MNQ",
        timestamp=1,
        side="Buy",
        original_action="Buy",
        quantity=1,
        price=100.0,
        commission=0.0,
        entry_exit="Entry",
        position_after="1 L",
        source_order_id=None,
        source_filename="f.csv",
        imported_at=1,
    )
    base.update(overrides)
    return Execution(**base)


def seed_executions(db_path: Path | str, execs: Sequence[Execution]) -> None:
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, execs)
    finally:
        conn.close()


def make_bar(**overrides) -> Bar:
    """Build a Bar with sane defaults; override any field by keyword."""
    base = dict(
        instrument="MNQ",
        timeframe="1m",
        time=60,
        open=100.0,
        high=100.5,
        low=99.5,
        close=100.0,
        volume=10,
        source="test",
    )
    base.update(overrides)
    return Bar(**base)


def make_position(**overrides) -> Position:
    """Build a Position with sane defaults; override any field by keyword."""
    base = dict(
        account="Sim101",
        instrument="MNQ",
        entry_execution_id="e",
        side="Long",
        entry_time=1000,
        exit_time=1060,
        quantity=1,
        entry_price=100.0,
        exit_price=101.0,
        points_pnl=1.0,
        dollars_pnl=5.0,
        commission=0.5,
        duration_minutes=1.0,
        execution_ids=["e"],
    )
    base.update(overrides)
    return Position(**base)


def seed_app_json(tmp_path: Path, extra: dict | None = None) -> Path:
    """Seed a minimal app.json in tmp_path. `extra` is merged at the top level."""
    body = {
        "data_dir": str(tmp_path),
        "db_path": str(tmp_path / "t.db"),
        "inbox_dir": str(tmp_path / "inbox"),
        "archive_dir": str(tmp_path / "archive"),
        "log_dir": str(tmp_path / "log"),
        "session": {
            "exchange_timezone": "America/Chicago",
            "trade_date_rollover": "17:00",
            "archive_job_time": "18:00",
        },
        "thread_pool": {"max_workers": 4},
        "scheduler": {"heartbeat_seconds": 30},
    }
    if extra:
        body.update(extra)
    path = tmp_path / "app.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path
