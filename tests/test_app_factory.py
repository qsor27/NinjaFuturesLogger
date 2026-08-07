import sqlite3


def test_create_app_without_background_services(app_and_services):
    app, services = app_and_services
    assert app is not None
    assert services is not None
    assert not services.scheduler_running()


def test_create_app_with_background_services(started_app_and_services):
    app, services = started_app_and_services
    assert services.scheduler_running()
    assert services.observer_alive()


def test_app_db_initialized_with_baseline_migration(app, tmp_config):
    conn = sqlite3.connect(tmp_config.db_path)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    conn.close()
    versions = {r[0] for r in rows}
    assert "001_baseline" in versions
