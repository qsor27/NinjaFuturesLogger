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
    # accounts lives on FilterDefaults (shared across /positions and /stats),
    # so it is intentionally NOT a field here.
    instrument: str = ""
    side: str = ""  # "" | "Long" | "Short"
    outcome: str = ""  # "" | "winner" | "loser" | "scratch" | "open"


class StatsFilterDefault(StrictModel):
    # accounts lives on FilterDefaults; see comment on PositionsFilterDefault.
    side: str = ""  # "" | "Long" | "Short"


class FilterDefaults(StrictModel):
    accounts: tuple[str, ...] = ()
    positions: PositionsFilterDefault | None = None
    stats: StatsFilterDefault | None = None

    @field_validator("accounts", mode="before")
    @classmethod
    def coerce_accounts_to_tuple(cls, v):
        if isinstance(v, list):
            return tuple(v)
        return v


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


def _migrate_filter_defaults(raw: dict) -> None:
    """In-place shape migration for legacy `filter_defaults` JSON.

    Old shape kept `accounts` nested inside `positions` and `stats` scopes.
    New shape hoists `accounts` up one level (shared across pages). This
    function finds any nested `accounts` keys, hoists the first one up,
    and drops them from the per-page scopes. Safe to call on already-new
    shapes — it's a no-op then.
    """
    fd = raw.get("filter_defaults")
    if not isinstance(fd, dict):
        return
    if "accounts" not in fd:
        for scope in ("positions", "stats"):
            nested = fd.get(scope)
            if isinstance(nested, dict) and "accounts" in nested:
                fd["accounts"] = nested["accounts"]
                break
    for scope in ("positions", "stats"):
        nested = fd.get(scope)
        if isinstance(nested, dict) and "accounts" in nested:
            del nested["accounts"]


def load_config(path: Path | str) -> Config:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    _migrate_filter_defaults(raw)
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

    `scope` must be one of "accounts", "positions", or "stats". `value` of
    None removes the scope entry. A non-None dict is validated against the
    matching Pydantic shape — unknown keys or wrong types raise
    ValidationError. All other Config fields are preserved by a
    read-modify-write under a module-level lock.

    For the "accounts" scope the value must be `{"accounts": [...]}`; the
    list gets stored at `filter_defaults.accounts` (not nested in a
    sub-scope).
    """
    if scope == "positions":
        validator = PositionsFilterDefault
    elif scope == "stats":
        validator = StatsFilterDefault
    elif scope == "accounts":
        # Validate via FilterDefaults so the accounts list goes through the
        # same coercion and strict-mode checks as on load.
        validator = None  # handled below
    else:
        raise ValueError(f"invalid filter-defaults scope: {scope!r}")

    if value is not None:
        if scope == "accounts":
            if set(value.keys()) != {"accounts"}:
                raise ValueError(
                    "accounts scope body must be exactly {'accounts': [...]}"
                )
            FilterDefaults(accounts=value["accounts"])  # validates the list
        else:
            validator(**value)

    path = Path(path)
    with _SAVE_LOCK:
        raw_text = path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        _migrate_filter_defaults(raw)
        fd = raw.setdefault("filter_defaults", {})
        if scope == "accounts":
            if value is None:
                fd.pop("accounts", None)
            else:
                fd["accounts"] = value["accounts"]
        else:
            if value is None:
                fd.pop(scope, None)
            else:
                fd[scope] = value
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))


def clear_all_filter_defaults(path: Path | str) -> None:
    """Remove the entire `filter_defaults` key from app.json."""
    path = Path(path)
    with _SAVE_LOCK:
        raw_text = path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        raw.pop("filter_defaults", None)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
