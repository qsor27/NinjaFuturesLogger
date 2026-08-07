from background import BackgroundServices


def test_start_and_stop_lifecycle(tmp_config):
    services = BackgroundServices(tmp_config)
    services.start()
    try:
        assert services.scheduler_running()
        assert services.observer_alive()
        assert services.pool_max_workers() == 2
    finally:
        services.stop()
    assert not services.scheduler_running()
    assert not services.observer_alive()


def test_heartbeat_job_is_registered(tmp_config):
    services = BackgroundServices(tmp_config)
    services.start()
    try:
        job_ids = [j.id for j in services.scheduler.get_jobs()]
        assert "heartbeat" in job_ids
    finally:
        services.stop()


def test_last_scheduler_tick_updates(tmp_config):
    services = BackgroundServices(tmp_config)
    services.start()
    try:
        services._heartbeat()
        assert services.last_scheduler_tick() is not None
    finally:
        services.stop()
