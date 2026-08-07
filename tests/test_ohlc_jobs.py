from concurrent.futures import ThreadPoolExecutor

import pytest

from services.ohlc.jobs import FetchJobRegistry
from tests.conftest import wait_until


@pytest.fixture
def pool():
    p = ThreadPoolExecutor(max_workers=2)
    yield p
    p.shutdown(wait=True, cancel_futures=True)


def test_unknown_job_id_is_not_found(pool):
    reg = FetchJobRegistry()
    assert reg.status("nope")["state"] == "not_found"


def test_submit_returns_unique_job_id(pool):
    reg = FetchJobRegistry()
    a = reg.submit(pool, lambda: None, meta={"x": 1})
    b = reg.submit(pool, lambda: None, meta={"x": 2})
    assert a != b


def test_submit_runs_function(pool):
    reg = FetchJobRegistry()
    seen = []
    job_id = reg.submit(pool, lambda: seen.append("ran"), meta={})
    assert wait_until(lambda: reg.status(job_id)["state"] == "done", timeout=2.0), (
        f"job {job_id} did not reach done"
    )
    assert seen == ["ran"]


def test_done_state(pool):
    reg = FetchJobRegistry()
    job_id = reg.submit(pool, lambda: 42, meta={"instrument": "MNQ"})
    assert wait_until(lambda: reg.status(job_id)["state"] == "done", timeout=2.0), (
        f"job {job_id} did not reach done"
    )
    snap = reg.status(job_id)
    assert snap["state"] == "done"
    assert snap["meta"] == {"instrument": "MNQ"}


def test_failed_state_carries_error(pool):
    reg = FetchJobRegistry()

    def boom():
        raise RuntimeError("nope")

    job_id = reg.submit(pool, boom, meta={})
    assert wait_until(lambda: reg.status(job_id)["state"] == "failed", timeout=2.0), (
        f"job {job_id} did not reach failed"
    )
    snap = reg.status(job_id)
    assert snap["state"] == "failed"
    assert "nope" in snap["error"]


def test_done_state_includes_fetch_result_summary(pool):
    """A fetch job that 'completes' having fetched nothing (breaker open,
    sources down) must not look identical to one that added bars — the UI
    needs status + bars_added to tell the user what actually happened."""
    from models.bar import FetchResult

    reg = FetchJobRegistry()
    job_id = reg.submit(
        pool,
        lambda: FetchResult(status="all_sources_unavailable", bars_added=0, attempts=[]),
        meta={},
    )
    assert wait_until(lambda: reg.status(job_id)["state"] == "done", timeout=2.0), (
        f"job {job_id} did not reach done"
    )
    snap = reg.status(job_id)
    assert snap["result"] == {"status": "all_sources_unavailable", "bars_added": 0}


def test_done_state_without_fetch_result_omits_summary(pool):
    reg = FetchJobRegistry()
    job_id = reg.submit(pool, lambda: 42, meta={})
    assert wait_until(lambda: reg.status(job_id)["state"] == "done", timeout=2.0), (
        f"job {job_id} did not reach done"
    )
    assert "result" not in reg.status(job_id)
