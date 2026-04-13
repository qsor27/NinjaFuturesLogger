from pathlib import Path

import pytest
from flask import Flask

from db import connect
from migrations import run_migrations
from models.position import IntegrityIssue
from routes.positions import build_positions_blueprint
from services.integrity_db import upsert_issue


@pytest.fixture
def app(tmp_path: Path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    run_migrations(conn, Path("migrations"))
    conn.close()
    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = str(db_path)
    app.register_blueprint(build_positions_blueprint())
    return app, db_path


def _issue(eid="abc"):
    return IntegrityIssue(
        account="Sim101",
        instrument="MNQ",
        execution_id=eid,
        severity="high",
        type="position_column_mismatch",
        description="x",
    )


def test_list_integrity_empty(app):
    app_, _ = app
    resp = app_.test_client().get("/api/integrity-issues")
    assert resp.status_code == 200
    assert resp.get_json() == {"issues": []}


def test_list_integrity_returns_open_issues(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _issue("a"), now=100)
        upsert_issue(conn, _issue("b"), now=100)
    finally:
        conn.close()
    resp = app_.test_client().get("/api/integrity-issues")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 2


def test_resolve_issue(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _issue("a"), now=100)
    finally:
        conn.close()
    resp = app_.test_client().post(
        "/api/integrity-issues/1/resolve", json={"note": "fixed"}
    )
    assert resp.status_code == 200
    resp2 = app_.test_client().get("/api/integrity-issues")
    assert resp2.get_json() == {"issues": []}


def test_ignore_issue(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _issue("a"), now=100)
    finally:
        conn.close()
    resp = app_.test_client().post(
        "/api/integrity-issues/1/ignore", json={"note": "known noise"}
    )
    assert resp.status_code == 200
    resp2 = app_.test_client().get("/api/integrity-issues")
    assert resp2.get_json() == {"issues": []}


def test_ignore_requires_note(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _issue("a"), now=100)
    finally:
        conn.close()
    resp = app_.test_client().post("/api/integrity-issues/1/ignore", json={})
    assert resp.status_code == 400
