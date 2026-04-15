import json
from pathlib import Path

from migrations_python import apply_json_migrations


def _seed(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "MNQ": {
                    "display_name": "Micro E-mini Nasdaq-100",
                    "multiplier": 2.0,
                    "tick_size": 0.25,
                    "sources": {
                        "yfinance": {"continuous": "MNQ=F", "contract_template": None},
                        "stooq": {"continuous": "mnq.f", "contract_template": None},
                    },
                    "session": {
                        "timezone": "America/Chicago",
                        "open": "17:00",
                        "close": "16:00",
                        "daily_break_start": "16:00",
                        "daily_break_end": "17:00",
                    },
                }
            }
        )
    )


def test_010_fills_yfinance_template(tmp_path):
    p = tmp_path / "instruments.json"
    _seed(p)
    apply_json_migrations(p)
    data = json.loads(p.read_text())
    assert data["MNQ"]["sources"]["yfinance"]["contract_template"] == "{ROOT}{M}{YY}.CME"
    assert data["MNQ"]["sources"]["stooq"]["contract_template"] is None


def test_010_is_idempotent(tmp_path):
    p = tmp_path / "instruments.json"
    _seed(p)
    apply_json_migrations(p)
    apply_json_migrations(p)
    data = json.loads(p.read_text())
    assert data["MNQ"]["sources"]["yfinance"]["contract_template"] == "{ROOT}{M}{YY}.CME"


def test_010_does_not_overwrite_existing_template(tmp_path):
    p = tmp_path / "instruments.json"
    _seed(p)
    data = json.loads(p.read_text())
    data["MNQ"]["sources"]["yfinance"]["contract_template"] = "custom.{ROOT}.{M}{YY}"
    p.write_text(json.dumps(data))
    apply_json_migrations(p)
    data = json.loads(p.read_text())
    assert data["MNQ"]["sources"]["yfinance"]["contract_template"] == "custom.{ROOT}.{M}{YY}"
