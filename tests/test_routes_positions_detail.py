import pytest

from services.flags import set_reviewed
from services.notes import upsert_note
from tests.conftest import make_execution, seed_executions


def _seed(db_path):
    seed_executions(
        db_path,
        [
            make_execution(
                "a",
                account="Sim",
                timestamp=100,
                price=100.0,
                imported_at=100,
            ),
            make_execution(
                "b",
                account="Sim",
                timestamp=200,
                side="Sell",
                original_action="Sell",
                price=101.0,
                entry_exit="Exit",
                position_after="-",
                imported_at=200,
            ),
        ],
    )


def test_detail_attaches_notes_and_reviewed(app, tmp_config):
    _seed(tmp_config.db_path)
    upsert_note(tmp_config.db_path, execution_id="a", note="setup", now=150)
    set_reviewed(tmp_config.db_path, execution_id="a", reviewed=True, now=151)
    resp = app.test_client().get("/api/positions/Sim/MNQ/a")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["position"]["entry_execution_id"] == "a"
    assert body["notes"] == {"a": "setup"}
    assert body["reviewed"] == {"a": True}
    assert body["custom_fields"] == {"entry": {}, "per_execution": [], "definitions": []}


def test_detail_not_found(client):
    resp = client.get("/api/positions/Sim/MNQ/nope")
    assert resp.status_code == 404


def test_detail_executions_endpoint(app, tmp_config):
    _seed(tmp_config.db_path)
    resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
    assert resp.status_code == 200
    body = resp.get_json()
    assert [e["nt_execution_id"] for e in body["executions"]] == ["a", "b"]


def test_executions_endpoint_entry_rows_have_null_pnl(app, tmp_config):
    _seed(tmp_config.db_path)
    resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
    assert resp.status_code == 200
    body = resp.get_json()
    entry = next(e for e in body["executions"] if e["entry_exit"] == "Entry")
    assert entry["avg_entry_price"] is None
    assert entry["pnl_points"] is None
    assert entry["pnl_dollars_net"] is None


def test_executions_endpoint_exit_rows_have_pnl(app, tmp_config):
    # MNQ Long: entry 100.0, exit 101.0, qty 1, commission 0
    # MNQ multiplier = 2.0
    # pnl_points = (101.0 - 100.0) * 1 * 1 = 1.0
    # pnl_dollars_net = 1.0 * 2.0 - 0.0 = 2.0
    _seed(tmp_config.db_path)
    resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
    assert resp.status_code == 200
    body = resp.get_json()
    exit_row = next(e for e in body["executions"] if e["entry_exit"] == "Exit")
    assert exit_row["avg_entry_price"] == pytest.approx(100.0)
    assert exit_row["pnl_points"] == pytest.approx(1.0)
    assert exit_row["pnl_dollars_net"] == pytest.approx(2.0)


def test_closing_fill_mislabeled_entry_in_csv_still_gets_pnl(app, tmp_config):
    # NT sometimes labels a closing fill "Entry" when its own position
    # tracking has drifted (seen in real data: MNQ SEP26 2026-07-13). The
    # walk decides what closes a position — the CSV label must not blank
    # the PnL columns on the detail page.
    seed_executions(
        tmp_config.db_path,
        [
            make_execution(
                "a",
                account="Sim",
                timestamp=100,
                quantity=2,
                price=100.0,
                position_after="2 L",
                imported_at=100,
            ),
            make_execution(
                "b",
                account="Sim",
                timestamp=200,
                side="Sell",
                original_action="Sell",
                quantity=1,
                price=101.0,
                entry_exit="Exit",
                position_after="1 L",
                imported_at=200,
            ),
            make_execution(
                "c",
                account="Sim",
                timestamp=300,
                side="Sell",
                original_action="Sell",
                quantity=1,
                price=102.0,
                entry_exit="Entry",
                position_after="2 S",
                imported_at=300,
            ),
        ],
    )
    resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
    assert resp.status_code == 200
    rows = {e["nt_execution_id"]: e for e in resp.get_json()["executions"]}
    assert rows["c"]["entry_exit"] == "Exit"
    assert rows["c"]["avg_entry_price"] == pytest.approx(100.0)
    assert rows["c"]["pnl_points"] == pytest.approx(2.0)
    assert rows["c"]["pnl_dollars_net"] == pytest.approx(4.0)  # 2 pts × 2.0 multiplier


def test_reversal_split_renders_suffixed_rows_with_split_quantities(app, tmp_config):
    # Long 2, then Sell 5 reverses into Short 3. Doc 12 acceptance #6: the
    # execution list shows #close/#open rows for split fills. The long
    # position shows b#close (qty 2, proportional commission, PnL); the
    # short position shows b#open (qty 3, no PnL — it's an entry).
    seed_executions(
        tmp_config.db_path,
        [
            make_execution(
                "a",
                account="Sim",
                timestamp=100,
                quantity=2,
                price=100.0,
                position_after="2 L",
                imported_at=100,
            ),
            make_execution(
                "b",
                account="Sim",
                timestamp=200,
                side="Sell",
                original_action="Sell",
                quantity=5,
                price=101.0,
                commission=5.0,
                entry_exit="Entry",
                position_after="3 S",
                imported_at=200,
            ),
        ],
    )
    client = app.test_client()

    resp = client.get("/api/positions/Sim/MNQ/a/executions")
    assert resp.status_code == 200
    long_rows = resp.get_json()["executions"]
    assert [e["nt_execution_id"] for e in long_rows] == ["a", "b#close"]
    close = long_rows[1]
    assert close["quantity"] == 2
    assert close["commission"] == pytest.approx(2.0)  # 5.0 × 2/5
    assert close["entry_exit"] == "Exit"
    assert close["pnl_points"] == pytest.approx(2.0)  # (101-100) × 2
    assert close["pnl_dollars_net"] == pytest.approx(2.0)  # 2 × 2.0 mult − 2.0 comm

    resp = client.get("/api/positions/Sim/MNQ/b%23open/executions")
    assert resp.status_code == 200
    short_rows = resp.get_json()["executions"]
    assert [e["nt_execution_id"] for e in short_rows] == ["b#open"]
    opener = short_rows[0]
    assert opener["quantity"] == 3
    assert opener["commission"] == pytest.approx(3.0)  # 5.0 × 3/5
    assert opener["entry_exit"] == "Entry"
    assert opener["pnl_points"] is None
    assert opener["pnl_dollars_net"] is None


def test_executions_endpoint_exit_pnl_uses_commission_fallback(app, tmp_config, tmp_path):
    import json

    from services.instruments import set_registry_path

    instruments_json = tmp_path / "instruments.json"
    instruments_json.write_text(
        json.dumps(
            {
                "MNQ": {
                    "display_name": "Micro E-mini Nasdaq-100",
                    "multiplier": 2.0,
                    "tick_size": 0.25,
                    "commission_per_contract": 1.08,
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
    set_registry_path(instruments_json)
    _seed(tmp_config.db_path)  # seeds MNQ with commission=0.0
    resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
    body = resp.get_json()
    exit_row = next(e for e in body["executions"] if e["entry_exit"] == "Exit")
    # pnl_points = 1.0, multiplier = 2.0, eff_comm = 1.08 × 1 = 1.08
    # pnl_dollars_net = 2.0 - 1.08 = 0.92
    assert exit_row["pnl_dollars_net"] == pytest.approx(0.92)
