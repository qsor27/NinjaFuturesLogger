import sqlite3

from app import create_app


def test_create_app_without_background_services(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    assert app is not None
    assert services is not None
    assert not services.scheduler_running()


def test_create_app_with_background_services(tmp_config):
    app, services = create_app(tmp_config, start_background=True)
    try:
        assert services.scheduler_running()
        assert services.observer_alive()
    finally:
        services.stop()


def test_app_db_initialized_with_baseline_migration(tmp_config):
    create_app(tmp_config, start_background=False)
    conn = sqlite3.connect(tmp_config.db_path)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    conn.close()
    versions = {r[0] for r in rows}
    assert "001_baseline" in versions
