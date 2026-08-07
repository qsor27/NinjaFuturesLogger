from pathlib import Path

from db import connect
from tests.conftest import wait_until, write_ninja_csv


def test_integrity_hook_runs_after_tick_and_records_issues(started_app_and_services, tmp_config):
    app, services = started_app_and_services
    bad_row = (
        "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,badpos1,Entry,99 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
    )
    path = Path(tmp_config.inbox_dir) / "NinjaTrader_Executions_20260413.csv"
    write_ninja_csv(path, [bad_row])

    def _issues_detected() -> bool:
        conn = connect(tmp_config.db_path)
        try:
            issue_count = conn.execute(
                "SELECT COUNT(*) FROM integrity_issues "
                "WHERE execution_id = 'badpos1' AND resolved_at IS NULL"
            ).fetchone()[0]
            return issue_count >= 1
        finally:
            conn.close()

    assert wait_until(_issues_detected)


def test_positions_route_returns_computed_positions(app, tmp_config):
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
    assert body["page"]["total"] == 1
    assert body["positions"][0]["entry_execution_id"] == "a"
