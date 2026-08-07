from tests.conftest import make_execution, seed_executions


def _seed(db_path):
    seed_executions(
        db_path,
        [
            make_execution("abc"),
        ],
    )


def test_patch_note_creates(app, tmp_config):
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


def test_patch_note_requires_string(app, tmp_config):
    _seed(tmp_config.db_path)
    resp = app.test_client().patch("/api/executions/abc/note", json={"note": 123})
    assert resp.status_code == 400


def test_patch_note_unknown_execution_404(client):
    resp = client.patch(
        "/api/executions/missing/note",
        json={"note": "x"},
    )
    assert resp.status_code == 404


def test_patch_reviewed_sets_true(app, tmp_config):
    _seed(tmp_config.db_path)
    resp = app.test_client().patch(
        "/api/executions/abc/reviewed",
        json={"reviewed": True},
    )
    assert resp.status_code == 200
    from services.flags import get_flag

    assert get_flag(tmp_config.db_path, "abc")["reviewed"] is True


def test_patch_reviewed_sets_false(app, tmp_config):
    _seed(tmp_config.db_path)
    app.test_client().patch("/api/executions/abc/reviewed", json={"reviewed": True})
    resp = app.test_client().patch("/api/executions/abc/reviewed", json={"reviewed": False})
    assert resp.status_code == 200
    from services.flags import get_flag

    assert get_flag(tmp_config.db_path, "abc")["reviewed"] is False


def test_patch_reviewed_requires_bool(app, tmp_config):
    _seed(tmp_config.db_path)
    resp = app.test_client().patch("/api/executions/abc/reviewed", json={"reviewed": "yes"})
    assert resp.status_code == 400


def test_patch_reviewed_unknown_execution_404(client):
    resp = client.patch(
        "/api/executions/missing/reviewed",
        json={"reviewed": True},
    )
    assert resp.status_code == 404
