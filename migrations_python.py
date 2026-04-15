"""JSON-side migrations applied on app startup after SQL migrations.

Each function in `_STEPS` is idempotent. Run in list order. A migration
should check current state before writing anything — callers re-run this
on every startup.
"""

import json
from pathlib import Path

_YFINANCE_TEMPLATE = "{ROOT}{M}{YY}.CME"


def _fill_yfinance_contract_templates(data: dict) -> bool:
    """Return True if anything changed."""
    changed = False
    for _root, cfg in data.items():
        sources = cfg.get("sources", {})
        yf = sources.get("yfinance")
        if yf is None:
            continue
        if yf.get("contract_template") is None:
            yf["contract_template"] = _YFINANCE_TEMPLATE
            changed = True
    return changed


_STEPS = [
    ("fill_yfinance_contract_templates", _fill_yfinance_contract_templates),
]


def apply_json_migrations(instruments_json_path: Path | str) -> list[str]:
    """Apply all JSON migration steps. Returns names of steps that changed anything."""
    path = Path(instruments_json_path)
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw) if raw.strip() else {}
    applied: list[str] = []
    for name, fn in _STEPS:
        if fn(data):
            applied.append(name)
    if applied:
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return applied
