"""Integration sanity: ingest a CSV, seed 1m bars over the computed window,
and verify the mfe-mae endpoint reports the expected numbers."""

from pathlib import Path
from zoneinfo import ZoneInfo

from app import create_app
from db import connect
from models.bar import Bar
from services.import_pipeline import ImportPipeline
from services.ohlc.store import insert_many

TZ = ZoneInfo("America/Chicago")

CSV_HEADER = (
    "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
    "Commission,Rate,Account,Connection,TradeValidation\n"
)
CSV_BODY = (
    "MNQ,Buy,1,100.00,1/15/2025 2:45:30 PM,E1,Entry,1 L,12345,Manual Entry,$0.00,1,Sim101,Apex Trader Funding ,\n"
    "MNQ,Sell,1,102.00,1/15/2025 3:00:00 PM,E2,Exit,-,12346,Manual Exit,$0.00,1,Sim101,Apex Trader Funding ,\n"
)


def test_mfe_mae_integration_end_to_end(tmp_config, tmp_path):
    # 1) Build the app (runs migrations).
    app, _services = create_app(tmp_config, start_background=False)

    # 2) Drop a CSV into inbox and ingest it via the pipeline.
    csv_path = Path(tmp_config.inbox_dir) / "NinjaTrader_Executions_20250115.csv"
    csv_path.write_text(CSV_HEADER + CSV_BODY, encoding="utf-8")
    pipeline = ImportPipeline(
        db_path=tmp_config.db_path,
        trader_tz=TZ,
        post_tick_hooks=[],
    )
    result = pipeline.ingest_tick(csv_path)
    assert result.rows_inserted == 2

    # 3) Read back the timestamps so we can seed bars against the real unix
    #    seconds the parser produced (avoids hand-computing CST→UTC).
    conn = connect(tmp_config.db_path)
    try:
        rows = conn.execute(
            "SELECT timestamp FROM executions WHERE account='Sim101' ORDER BY timestamp"
        ).fetchall()
        entry_ts = rows[0]["timestamp"]
        exit_ts = rows[-1]["timestamp"]

        # 4) Seed 1m bars covering the window. MNQ multiplier is 2, so:
        #    MFE = (103-100) * 1 * 2 = $6 when a bar high hits 103.
        #    MAE = (99-100) * 1 * 2 = -$2 when a bar low hits 99.
        #    Realized = (102-100) * 1 * 2 = $4.
        bars = []
        t = entry_ts + 60
        while t < exit_ts:
            # Pick high/low so one bar drives the MFE and another drives the MAE.
            if t == entry_ts + 120:
                high, low = 103.0, 100.5
            elif t == entry_ts + 240:
                high, low = 100.5, 99.0
            else:
                high, low = 101.0, 100.0
            bars.append(
                Bar(
                    instrument="MNQ",
                    timeframe="1m",
                    time=t,
                    open=100.5,
                    high=high,
                    low=low,
                    close=101.0,
                    volume=0,
                    source="test",
                )
            )
            t += 60
        insert_many(conn, bars)
        conn.commit()
    finally:
        conn.close()

    # 5) Hit the endpoint.
    client = app.test_client()
    resp = client.get("/api/positions/Sim101/MNQ/E1/mfe-mae")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["result"] is not None
    r = body["result"]
    assert r["mfe_dollars"] == 6.0
    assert r["mae_dollars"] == -2.0
    assert r["mfe_price"] == 103.0
    assert r["mae_price"] == 99.0
    # Coverage should be high enough to pass the 0.8 threshold (we seeded most
    # of the window). Just assert it's above 0.5 as a loose sanity check —
    # the exact expected-slot count depends on the MNQ session calendar.
    assert r["coverage"] >= 0.5
