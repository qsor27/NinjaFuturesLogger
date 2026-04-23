import json
import os
import threading
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import field_validator

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


class PositionsFilterDefault(StrictModel):
    accounts: tuple[str, ...] = ()
    instrument: str = ""
    side: str = ""  # "" | "Long" | "Short"
    outcome: str = ""  # "" | "winner" | "loser" | "scratch" | "open"

    @field_validator("accounts", mode="before")
    @classmethod
    def coerce_accounts_to_tuple(cls, v):
        if isinstance(v, list):
            return tuple(v)
        return v


class StatsFilterDefault(StrictModel):
    accounts: tuple[str, ...] = ()
    side: str = ""  # "" | "Long" | "Short"

    @field_validator("accounts", mode="before")
    @classmethod
    def coerce_accounts_to_tuple(cls, v):
        if isinstance(v, list):
            return tuple(v)
        return v


class FilterDefaults(StrictModel):
    positions: PositionsFilterDefault | None = None
    stats: StatsFilterDefault | None = None


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
    filter_defaults: FilterDefaults = FilterDefaults()


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


def save_theme(path: Path | str, value: str) -> None:
    """Update the top-level `theme` field in app.json via atomic tmp+rename.

    Validates that value is either "dark" or "light". All other Config
    fields are preserved by a read-modify-write under a module-level lock.
    """
    if value not in ("dark", "light"):
        raise ValueError(f"invalid theme: {value!r}")

    path = Path(path)
    with _SAVE_LOCK:
        raw_text = path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        raw["theme"] = value
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))


def save_filter_default(
    path: Path | str,
    scope: str,
    value: dict | None,
) -> None:
    """Update `filter_defaults.<scope>` in app.json via atomic tmp+rename.

    `scope` must be one of "positions" or "stats". `value` of None removes
    the scope entry. A non-None dict is validated against the per-scope
    Pydantic model — unknown keys or wrong types raise ValidationError.
    All other Config fields are preserved by a read-modify-write under a
    module-level lock.
    """
    if scope == "positions":
        model_cls = PositionsFilterDefault
    elif scope == "stats":
        model_cls = StatsFilterDefault
    else:
        raise ValueError(f"invalid filter-defaults scope: {scope!r}")

    if value is not None:
        model_cls(**value)  # raises ValidationError on bad input

    path = Path(path)
    with _SAVE_LOCK:
        raw_text = path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        fd = raw.setdefault("filter_defaults", {})
        if value is None:
            fd.pop(scope, None)
        else:
            fd[scope] = value
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
