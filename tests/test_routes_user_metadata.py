from app import create_app
from db import connect
from models.execution import Execution
from services.import_db import bulk_insert_executions


def _seed(db_path):
    conn = connect(db_path)
    try:
        bulk_insert_executions(
            conn,
            [
                Execution(
                    nt_execution_id="abc",
                    account="Sim",
                    instrument="MNQ",
                    timestamp=1,
                    side="Buy",
                    original_action="Buy",
                    quantity=1,
                    price=100.0,
                    commission=0.0,
                    entry_exit="Entry",
                    position_after="1 L",
                    source_order_id=None,
                    source_filename="f.csv",
                    imported_at=1,
                )
            ],
        )
    finally:
        conn.close()


def test_patch_note_creates(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        resp = app.test_client().patch(
            "/api/executions/abc/note",
            json={"note": "hello"},
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}
        # Confirm persistence
        from services.notes import get_note
        got = get_note(tmp_config.db_path, "abc")
        assert got["note"] == "hello"
    finally:
        services.stop()


def test_patch_note_requires_string(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        resp = app.test_client().patch("/api/executions/abc/note", json={"note": 123})
        assert resp.status_code == 400
    finally:
        services.stop()


def test_patch_note_unknown_execution_404(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().patch(
            "/api/executions/missing/note",
            json={"note": "x"},
        )
        assert resp.status_code == 404
    finally:
        services.stop()


def test_patch_reviewed_sets_true(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        resp = app.test_client().patch(
            "/api/executions/abc/reviewed",
            json={"reviewed": True},
        )
        assert resp.status_code == 200
        from services.flags import get_flag
        assert get_flag(tmp_config.db_path, "abc")["reviewed"] is True
    finally:
        services.stop()


def test_patch_reviewed_sets_false(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        app.test_client().patch(
            "/api/executions/abc/reviewed", json={"reviewed": True}
        )
        resp = app.test_client().patch(
            "/api/executions/abc/reviewed", json={"reviewed": False}
        )
        assert resp.status_code == 200
        from services.flags import get_flag
        assert get_flag(tmp_config.db_path, "abc")["reviewed"] is False
    finally:
        services.stop()


def test_patch_reviewed_requires_bool(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        resp = app.test_client().patch(
            "/api/executions/abc/reviewed", json={"reviewed": "yes"}
        )
        assert resp.status_code == 400
    finally:
        services.stop()


def test_patch_reviewed_unknown_execution_404(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().patch(
            "/api/executions/missing/reviewed",
            json={"reviewed": True},
        )
        assert resp.status_code == 404
    finally:
        services.stop()
