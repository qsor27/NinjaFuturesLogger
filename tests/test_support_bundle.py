import io
import sqlite3
import zipfile
from pathlib import Path

from db import connect
from migrations import run_migrations
from services.support_bundle import build_bundle, snapshot_db


def _init_db(tmp_path: Path) -> Path:
    db = tmp_path / "trading_log.db"
    conn = connect(db)
    try:
        run_migrations(conn, Path("migrations"))
        conn.commit()
    finally:
        conn.close()
    return db


def test_snapshot_db_empty_returns_all_expected_keys(tmp_path: Path):
    db = _init_db(tmp_path)
    snap = snapshot_db(db, days=7, now=1_700_000_000)

    assert set(snap.keys()) == {
        "fetch_attempts",
        "fetch_source_attempts",
        "ohlc_gap_reports",
        "ohlc_breaker_state",
        "import_runs",
        "import_rejects",
        "integrity_issues",
        "schema_migrations",
    }
    for rows in snap.values():
        assert isinstance(rows, list)
    # schema_migrations has at least one row after run_migrations
    assert len(snap["schema_migrations"]) >= 1


def test_snapshot_db_windows_by_days(tmp_path: Path):
    db = _init_db(tmp_path)
    now = 1_700_000_000
    cutoff = now - 7 * 86400

    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO fetch_attempts"
        " (id, trigger, instrument, timeframe, range_start, range_end,"
        "  started_at, gaps_found, bars_written, final_status)"
        " VALUES (?, 'on_demand', 'MNQ', '1m', 0, 0, ?, 0, 0, 'ok')",
        ("keep", cutoff + 100),
    )
    conn.execute(
        "INSERT INTO fetch_attempts"
        " (id, trigger, instrument, timeframe, range_start, range_end,"
        "  started_at, gaps_found, bars_written, final_status)"
        " VALUES (?, 'on_demand', 'MNQ', '1m', 0, 0, ?, 0, 0, 'ok')",
        ("drop", cutoff - 100),
    )
    conn.commit()
    conn.close()

    snap = snapshot_db(db, days=7, now=now)
    ids = {row["id"] for row in snap["fetch_attempts"]}
    assert ids == {"keep"}


def test_snapshot_db_caps_row_count(tmp_path: Path):
    db = _init_db(tmp_path)
    now = 1_700_000_000
    conn = sqlite3.connect(db)
    for i in range(10_100):
        conn.execute(
            "INSERT INTO fetch_attempts"
            " (id, trigger, instrument, timeframe, range_start, range_end,"
            "  started_at, gaps_found, bars_written, final_status)"
            " VALUES (?, 'sweep', 'MNQ', '1m', 0, 0, ?, 0, 0, 'ok')",
            (f"a{i}", now - i),
        )
    conn.commit()
    conn.close()

    snap = snapshot_db(db, days=7, now=now)
    assert len(snap["fetch_attempts"]) == 10_000
    # Most-recent first: the newest 10k rows kept, older 100 dropped.
    ids = [r["id"] for r in snap["fetch_attempts"]]
    assert "a0" in ids
    assert "a10099" not in ids


def test_build_bundle_contains_expected_members(tmp_path: Path):
    db = _init_db(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "app.jsonl").write_text('{"level": "INFO", "message": "hi"}\n', encoding="utf-8")
    (log_dir / "app.jsonl.1").write_text(
        '{"level": "INFO", "message": "older"}\n', encoding="utf-8"
    )
    (log_dir / "unrelated.txt").write_text("ignore me", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "app.json").write_text('{"data_dir": "data"}', encoding="utf-8")
    (config_dir / "instruments.json").write_text('{"MNQ": {}}', encoding="utf-8")

    version = {"git_sha": "deadbeef", "built_at": "2026-04-23T12:00:00Z", "image_tag": "v1.2.3"}

    raw = build_bundle(
        db_path=db,
        log_dir=log_dir,
        config_dir=config_dir,
        version=version,
        days=7,
        now=1_700_000_000,
    )

    zf = zipfile.ZipFile(io.BytesIO(raw))
    names = set(zf.namelist())
    assert "version.json" in names
    assert "snapshot.json" in names
    assert "config/app.json" in names
    assert "config/instruments.json" in names
    assert "logs/app.jsonl" in names
    assert "logs/app.jsonl.1" in names
    assert "logs/unrelated.txt" not in names

    import json as _json

    version_payload = _json.loads(zf.read("version.json"))
    assert version_payload["git_sha"] == "deadbeef"

    snap_payload = _json.loads(zf.read("snapshot.json"))
    assert "fetch_attempts" in snap_payload
    assert "schema_migrations" in snap_payload


def test_build_bundle_missing_files_are_skipped(tmp_path: Path):
    db = _init_db(tmp_path)
    raw = build_bundle(
        db_path=db,
        log_dir=tmp_path / "does-not-exist",
        config_dir=tmp_path / "also-missing",
        version={"git_sha": "x", "built_at": "y", "image_tag": "z"},
        days=7,
        now=1_700_000_000,
    )
    zf = zipfile.ZipFile(io.BytesIO(raw))
    names = set(zf.namelist())
    assert "version.json" in names
    assert "snapshot.json" in names
    assert not any(n.startswith("logs/") for n in names)
    assert not any(n.startswith("config/") for n in names)


def test_build_bundle_includes_system_health_when_provided(tmp_path: Path):
    db = _init_db(tmp_path)
    snap = {"uptime_seconds": 42, "scheduler_running": True}
    raw = build_bundle(
        db_path=db,
        log_dir=tmp_path / "missing",
        config_dir=tmp_path / "missing",
        version={"git_sha": "x", "built_at": "y", "image_tag": "z"},
        days=7,
        now=1_700_000_000,
        system_health=snap,
    )
    zf = zipfile.ZipFile(io.BytesIO(raw))
    assert "system_health.json" in zf.namelist()
    import json as _json

    assert _json.loads(zf.read("system_health.json")) == snap


def test_build_bundle_omits_system_health_when_none(tmp_path: Path):
    db = _init_db(tmp_path)
    raw = build_bundle(
        db_path=db,
        log_dir=tmp_path / "missing",
        config_dir=tmp_path / "missing",
        version={"git_sha": "x", "built_at": "y", "image_tag": "z"},
        days=7,
        now=1_700_000_000,
    )
    zf = zipfile.ZipFile(io.BytesIO(raw))
    assert "system_health.json" not in zf.namelist()
