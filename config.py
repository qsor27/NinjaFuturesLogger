import json
import os
import threading
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from models.base import StrictModel

_SAVE_LOCK = threading.Lock()


class SessionConfig(StrictModel):
    exchange_timezone: str
    trade_date_rollover: str  # "HH:MM"
    archive_job_time: str  # "HH:MM"
    # Timezone the NinjaTrader machine exports CSV timestamps in. The CSV itself
    # has no tz info, so we need this to convert to UTC on ingest. When unset,
    # falls back to `exchange_timezone` for back-compat with older configs.
    source_timezone: str | None = None


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
    display_timezone: str | None = None
    theme: Literal["dark", "light"] = "dark"


def load_config(path: Path | str) -> Config:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Config(**raw)


def save_source_timezone(path: Path | str, value: str | None) -> None:
    """Update `session.source_timezone` in app.json via atomic tmp+rename."""
    if value is not None:
        try:
            ZoneInfo(value)
        except Exception as e:
            raise ValueError(f"invalid IANA timezone: {value!r}") from e

    path = Path(path)
    with _SAVE_LOCK:
        raw_text = path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        raw.setdefault("session", {})["source_timezone"] = value
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))


def save_display_timezone(path: Path | str, value: str | None) -> None:
    """Update the `display_timezone` field in app.json via atomic tmp+rename.

    Validates `value` by constructing `zoneinfo.ZoneInfo(value)`. Passes None
    through unchanged. All other Config fields are preserved by a
    read-modify-write under a module-level lock.
    """
    if value is not None:
        try:
            ZoneInfo(value)
        except Exception as e:
            raise ValueError(f"invalid IANA timezone: {value!r}") from e

    path = Path(path)
    with _SAVE_LOCK:
        raw_text = path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        raw["display_timezone"] = value
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
