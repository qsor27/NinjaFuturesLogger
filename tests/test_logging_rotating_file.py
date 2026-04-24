import json
import logging
from pathlib import Path

from logging_config import configure_logging, get_logger


def test_file_handler_writes_json_lines(tmp_path: Path):
    log_file = tmp_path / "app.jsonl"
    configure_logging(level="INFO", log_file=log_file)
    try:
        get_logger("test").info("hello", extra={"attempt_id": "abc"})
        for h in logging.getLogger().handlers:
            h.flush()

        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["level"] == "INFO"
        assert payload["component"] == "test"
        assert payload["message"] == "hello"
        assert payload["attempt_id"] == "abc"
    finally:
        for h in list(logging.getLogger().handlers):
            h.close()
            logging.getLogger().removeHandler(h)


def test_file_handler_omitted_when_no_path(tmp_path: Path):
    configure_logging(level="INFO")
    try:
        from logging.handlers import RotatingFileHandler

        file_handlers = [
            h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)
        ]
        assert file_handlers == []
    finally:
        for h in list(logging.getLogger().handlers):
            h.close()
            logging.getLogger().removeHandler(h)


def test_file_handler_rotates_by_size(tmp_path: Path):
    log_file = tmp_path / "app.jsonl"
    configure_logging(level="INFO", log_file=log_file, max_bytes=200, backup_count=2)
    try:
        log = get_logger("rot")
        for i in range(40):
            log.info("x" * 50, extra={"i": i})
        for h in logging.getLogger().handlers:
            h.flush()
        assert log_file.exists()
        rotated = list(tmp_path.glob("app.jsonl.*"))
        assert len(rotated) >= 1
        assert len(rotated) <= 2
    finally:
        for h in list(logging.getLogger().handlers):
            h.close()
            logging.getLogger().removeHandler(h)


def test_create_app_attaches_file_handler(tmp_path: Path, monkeypatch):
    from logging.handlers import RotatingFileHandler

    from app import create_app
    from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig

    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "archive").mkdir()
    (data_dir / "logs").mkdir()

    cfg = Config(
        data_dir=str(data_dir),
        db_path=str(data_dir / "trading_log.db"),
        inbox_dir=str(data_dir / "inbox"),
        archive_dir=str(data_dir / "archive"),
        log_dir=str(data_dir / "logs"),
        session=SessionConfig(
            exchange_timezone="America/Chicago",
            trade_date_rollover="16:00",
            archive_job_time="18:00",
        ),
        thread_pool=ThreadPoolConfig(max_workers=4),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
    )

    try:
        app, services = create_app(cfg, start_background=False)
        root = logging.getLogger()
        rfhs = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
        assert len(rfhs) == 1
        assert Path(rfhs[0].baseFilename) == data_dir / "logs" / "app.jsonl"
    finally:
        for h in list(logging.getLogger().handlers):
            h.close()
            logging.getLogger().removeHandler(h)
