from app import create_app


def _create_group(client, members, label=None):
    body = {"members": members}
    if label is not None:
        body["label"] = label
    return client.post("/api/links", json=body)


def test_create_group_returns_id(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = _create_group(
            app.test_client(),
            members=[{"account": "A", "instrument": "MNQ", "entry_execution_id": "e1"}],
            label="setup",
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert isinstance(body["link_group_id"], int)
    finally:
        services.stop()


def test_create_group_rejects_empty_members(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().post("/api/links", json={"members": []})
        assert resp.status_code == 400
    finally:
        services.stop()


def test_create_group_rejects_missing_members_key(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().post("/api/links", json={"label": "x"})
        assert resp.status_code == 400
    finally:
        services.stop()


def test_create_group_rejects_malformed_member(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().post(
            "/api/links",
            json={"members": [{"account": "A"}]},  # missing instrument, entry_execution_id
        )
        assert resp.status_code == 400
    finally:
        services.stop()


def test_get_group_detail(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        create = _create_group(
            app.test_client(),
            members=[
                {"account": "A", "instrument": "MNQ", "entry_execution_id": "e1"},
                {"account": "A", "instrument": "MNQ", "entry_execution_id": "e2"},
            ],
            label="idea",
        )
        gid = create.get_json()["link_group_id"]
        resp = app.test_client().get(f"/api/links/{gid}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["link_group_id"] == gid
        assert body["label"] == "idea"
        assert len(body["members"]) == 2
    finally:
        services.stop()


def test_get_group_missing_404(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/links/9999")
        assert resp.status_code == 404
    finally:
        services.stop()


def test_list_groups(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        client = app.test_client()
        _create_group(client, [{"account": "A", "instrument": "M", "entry_execution_id": "a"}])
        _create_group(client, [{"account": "A", "instrument": "M", "entry_execution_id": "b"}])
        resp = client.get("/api/links")
        body = resp.get_json()
        assert len(body["groups"]) == 2
    finally:
        services.stop()


def test_patch_group_rename(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        client = app.test_client()
        create = _create_group(
            client, [{"account": "A", "instrument": "M", "entry_execution_id": "a"}]
        )
        gid = create.get_json()["link_group_id"]
        resp = client.patch(f"/api/links/{gid}", json={"label": "renamed"})
        assert resp.status_code == 200
        assert client.get(f"/api/links/{gid}").get_json()["label"] == "renamed"
    finally:
        services.stop()


def test_patch_group_add_members(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        client = app.test_client()
        create = _create_group(
            client, [{"account": "A", "instrument": "M", "entry_execution_id": "a"}]
        )
        gid = create.get_json()["link_group_id"]
        resp = client.patch(
            f"/api/links/{gid}",
            json={"add_members": [{"account": "A", "instrument": "M", "entry_execution_id": "b"}]},
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/links/{gid}").get_json()
        assert [m["entry_execution_id"] for m in detail["members"]] == ["a", "b"]
    finally:
        services.stop()


def test_patch_group_remove_member(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        client = app.test_client()
        create = _create_group(
            client,
            [
                {"account": "A", "instrument": "M", "entry_execution_id": "a"},
                {"account": "A", "instrument": "M", "entry_execution_id": "b"},
            ],
        )
        gid = create.get_json()["link_group_id"]
        resp = client.patch(
            f"/api/links/{gid}",
            json={
                "remove_members": [{"account": "A", "instrument": "M", "entry_execution_id": "a"}]
            },
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/links/{gid}").get_json()
        assert [m["entry_execution_id"] for m in detail["members"]] == ["b"]
    finally:
        services.stop()


def test_delete_group(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        client = app.test_client()
        create = _create_group(
            client, [{"account": "A", "instrument": "M", "entry_execution_id": "a"}]
        )
        gid = create.get_json()["link_group_id"]
        resp = client.delete(f"/api/links/{gid}")
        assert resp.status_code == 200
        assert client.get(f"/api/links/{gid}").status_code == 404
    finally:
        services.stop()
