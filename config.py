import json
from pathlib import Path

from models.base import StrictModel


class SessionConfig(StrictModel):
    exchange_timezone: str
    trade_date_rollover: str  # "HH:MM"
    archive_job_time: str     # "HH:MM"


class ThreadPoolConfig(StrictModel):
    max_workers: int


class SchedulerConfig(StrictModel):
    heartbeat_seconds: int


class Config(StrictModel):
    data_dir: str
    db_path: str
    inbox_dir: str
    archive_dir: str
    log_dir: str
    session: SessionConfig
    thread_pool: ThreadPoolConfig
    scheduler: SchedulerConfig


def load_config(path: Path | str) -> Config:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Config(**raw)
