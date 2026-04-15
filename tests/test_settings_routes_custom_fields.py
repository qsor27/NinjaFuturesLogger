import json
from pathlib import Path


def _setup_app(tmp_path: Path):
    from app import create_app
    from config import load_config

    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "archive").mkdir()
    (data_dir / "log").mkdir()
    app_json = data_dir / "config" / "app.json"
    app_json.write_text(
        json.dumps(
            {
                "data_dir": str(data_dir),
                "db_path": str(data_dir / "ftl.db"),
                "inbox_dir": str(data_dir / "inbox"),
                "archive_dir": str(data_dir / "archive"),
                "log_dir": str(data_dir / "log"),
                "session": {
                    "exchange_timezone": "America/Chicago",
                    "trade_date_rollover": "17:00",
                    "archive_job_time": "18:00",
                },
                "thread_pool": {"max_workers": 2},
                "scheduler": {"heartbeat_seconds": 30},
            }
        )
    )
    return create_app(load_config(app_json))[0].test_client()


def _seed_execution(tmp_path: Path, eid: str = "E1"):
    import sqlite3

    db_path = tmp_path / "data" / "ftl.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO executions (nt_execution_id, account, instrument, timestamp, side,"
        " original_action, quantity, price, commission, entry_exit, position_after,"
        " source_order_id, source_filename, imported_at) VALUES "
        "(?, 'Sim', 'MES', 1700000000, 'Buy', 'Buy', 1, 4500.0, 2.50, 'Entry', 1, 'O', 'f.csv', 1700000000)",
        (eid,),
    )
    conn.execute("COMMIT")
    conn.close()


def test_list_custom_fields_empty(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.get("/api/custom-fields")
    assert res.status_code == 200
    assert res.get_json() == {"fields": []}


def test_create_custom_field(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.post(
        "/api/custom-fields",
        json={
            "name": "setup",
            "field_type": "dropdown",
            "display_order": 0,
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["field"]["name"] == "setup"

    res = client.get("/api/custom-fields")
    assert len(res.get_json()["fields"]) == 1


def test_create_custom_field_duplicate_name_409(tmp_path: Path):
    client = _setup_app(tmp_path)
    client.post("/api/custom-fields", json={"name": "setup", "field_type": "text"})
    res = client.post("/api/custom-fields", json={"name": "setup", "field_type": "text"})
    assert res.status_code == 409


def test_update_custom_field_name(tmp_path: Path):
    client = _setup_app(tmp_path)
    fid = client.post(
        "/api/custom-fields",
        json={
            "name": "setup",
            "field_type": "text",
        },
    ).get_json()["field"]["field_id"]
    res = client.put(f"/api/custom-fields/{fid}", json={"name": "Setup Type"})
    assert res.status_code == 200
    assert res.get_json()["field"]["name"] == "Setup Type"


def test_delete_custom_field_two_step(tmp_path: Path):
    client = _setup_app(tmp_path)
    fid = client.post(
        "/api/custom-fields",
        json={
            "name": "setup",
            "field_type": "text",
        },
    ).get_json()["field"]["field_id"]
    res = client.delete(f"/api/custom-fields/{fid}")
    assert res.status_code == 409
    assert res.get_json()["affected_executions"] == 0
    res = client.delete(f"/api/custom-fields/{fid}?confirm_count=0")
    assert res.status_code == 204


def test_replace_options_round_trip(tmp_path: Path):
    client = _setup_app(tmp_path)
    fid = client.post(
        "/api/custom-fields",
        json={
            "name": "setup",
            "field_type": "dropdown",
        },
    ).get_json()["field"]["field_id"]
    res = client.put(
        f"/api/custom-fields/{fid}/options",
        json={
            "options": [
                {"value": "Breakout", "display_order": 0},
                {"value": "Reversal", "display_order": 1},
            ],
        },
    )
    assert res.status_code == 200
    assert [o["value"] for o in res.get_json()["options"]] == ["Breakout", "Reversal"]

    res = client.get(f"/api/custom-fields/{fid}/options")
    assert len(res.get_json()["options"]) == 2


def test_get_execution_custom_fields_empty(tmp_path: Path):
    client = _setup_app(tmp_path)
    _seed_execution(tmp_path)
    res = client.get("/api/executions/E1/custom-fields")
    assert res.status_code == 200
    assert res.get_json() == {"values": {}}


def test_put_then_get_execution_custom_field_text(tmp_path: Path):
    client = _setup_app(tmp_path)
    _seed_execution(tmp_path)
    fid = client.post(
        "/api/custom-fields",
        json={
            "name": "setup",
            "field_type": "text",
        },
    ).get_json()["field"]["field_id"]

    res = client.put(
        f"/api/executions/E1/custom-fields/{fid}",
        json={"value": "A+ setup"},
    )
    assert res.status_code == 200

    res = client.get("/api/executions/E1/custom-fields")
    assert res.get_json()["values"] == {str(fid): "A+ setup"}


def test_put_execution_custom_field_empty_deletes(tmp_path: Path):
    client = _setup_app(tmp_path)
    _seed_execution(tmp_path)
    fid = client.post(
        "/api/custom-fields",
        json={
            "name": "setup",
            "field_type": "text",
        },
    ).get_json()["field"]["field_id"]
    client.put(f"/api/executions/E1/custom-fields/{fid}", json={"value": "A+"})
    client.put(f"/api/executions/E1/custom-fields/{fid}", json={"value": ""})
    res = client.get("/api/executions/E1/custom-fields")
    assert res.get_json()["values"] == {}


def test_put_execution_custom_field_unknown_field_400(tmp_path: Path):
    client = _setup_app(tmp_path)
    _seed_execution(tmp_path)
    res = client.put("/api/executions/E1/custom-fields/999", json={"value": "x"})
    assert res.status_code == 400


def test_put_execution_custom_field_split_suffix_lands_on_parent(tmp_path: Path):
    client = _setup_app(tmp_path)
    _seed_execution(tmp_path)
    fid = client.post(
        "/api/custom-fields",
        json={
            "name": "setup",
            "field_type": "text",
        },
    ).get_json()["field"]["field_id"]
    res = client.put(
        f"/api/executions/E1%23close/custom-fields/{fid}",
        json={"value": "B-"},
    )
    assert res.status_code == 200
    res = client.get("/api/executions/E1/custom-fields")
    assert res.get_json()["values"] == {str(fid): "B-"}
