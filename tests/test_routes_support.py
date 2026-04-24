import io
import zipfile
from pathlib import Path

from app import create_app
from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig


def _cfg(tmp_path: Path) -> Config:
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "archive").mkdir()
    (data_dir / "logs").mkdir()
    (data_dir / "config" / "app.json").write_text('{"data_dir": "data"}', encoding="utf-8")
    return Config(
        data_dir=str(data_dir),
        db_path=str(data_dir / "trading_log.db"),
        inbox_dir=str(data_dir / "inbox"),
        archive_dir=str(data_dir / "archive"),
        log_dir=str(data_dir / "logs"),
        session=SessionConfig(
            exchange_timezone="America/Chicago",
            trade_date_rollover="16:00",
            archive_job_time="18:00",
        ),
        thread_pool=ThreadPoolConfig(max_workers=4),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
    )


def test_support_bundle_returns_zip(tmp_path: Path):
    cfg = _cfg(tmp_path)
    app, _services = create_app(cfg, start_background=False)
    client = app.test_client()

    resp = client.get("/api/support/bundle")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "support-bundle" in resp.headers["Content-Disposition"]

    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    names = set(zf.namelist())
    assert "version.json" in names
    assert "snapshot.json" in names
    assert "system_health.json" in names
    assert "config/app.json" in names


def test_support_bundle_honors_days_param(tmp_path: Path):
    cfg = _cfg(tmp_path)
    app, _services = create_app(cfg, start_background=False)
    client = app.test_client()

    resp = client.get("/api/support/bundle?days=1")
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    assert "snapshot.json" in zf.namelist()


def test_support_bundle_rejects_invalid_days(tmp_path: Path):
    cfg = _cfg(tmp_path)
    app, _services = create_app(cfg, start_background=False)
    client = app.test_client()

    resp = client.get("/api/support/bundle?days=abc")
    assert resp.status_code == 400

    resp = client.get("/api/support/bundle?days=0")
    assert resp.status_code == 400

    resp = client.get("/api/support/bundle?days=400")
    assert resp.status_code == 400
