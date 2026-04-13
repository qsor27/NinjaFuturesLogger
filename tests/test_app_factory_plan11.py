import time
from pathlib import Path

from app import create_app
from db import connect


def test_integrity_hook_runs_after_tick_and_records_issues(tmp_config):
    app, services = create_app(tmp_config, start_background=True)
    try:
        header = (
            "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
            "Commission,Rate,Account,Connection,TradeValidation\n"
        )
        bad_row = (
            "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,badpos1,Entry,99 L,"
            "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
        )
        path = Path(tmp_config.inbox_dir) / "NinjaTrader_Executions_20260413.csv"
        path.write_text(header + bad_row, encoding="utf-8")

        deadline = time.time() + 3.0
        issue_count = 0
        while time.time() < deadline:
            conn = connect(tmp_config.db_path)
            try:
                issue_count = conn.execute(
                    "SELECT COUNT(*) FROM integrity_issues "
                    "WHERE execution_id = 'badpos1' AND resolved_at IS NULL"
                ).fetchone()[0]
            finally:
                conn.close()
            if issue_count >= 1:
                break
            time.sleep(0.05)
        assert issue_count == 1
    finally:
        services.stop()


def test_positions_route_returns_computed_positions(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    db_path = tmp_config.db_path

    from models.execution import Execution
    from services.import_db import bulk_insert_executions

    conn = connect(db_path)
    try:
        bulk_insert_executions(
            conn,
            [
                Execution(
                    nt_execution_id="a",
                    account="Sim101",
                    instrument="MNQ",
                    timestamp=100,
                    side="Buy",
                    original_action="Buy",
                    quantity=1,
                    price=4000.0,
                    commission=0.0,
                    entry_exit="Entry",
                    position_after="1 L",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=100,
                ),
                Execution(
                    nt_execution_id="b",
                    account="Sim101",
                    instrument="MNQ",
                    timestamp=200,
                    side="Sell",
                    original_action="Sell",
                    quantity=1,
                    price=4010.0,
                    commission=0.0,
                    entry_exit="Exit",
                    position_after="-",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=200,
                ),
            ],
        )
    finally:
        conn.close()

    resp = app.test_client().get("/api/positions")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["positions"]) == 1
    assert body["positions"][0]["entry_execution_id"] == "a"
