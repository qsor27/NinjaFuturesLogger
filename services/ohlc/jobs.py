import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor


class FetchJobRegistry:
    """In-memory registry of background fetch jobs.

    Single-process; restart wipes it. Plan 17's monitoring page may persist
    a summary later, but for now the only consumer is the polling client
    on the chart page (plan 13).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._futures: dict[str, Future] = {}
        self._meta: dict[str, dict] = {}

    def submit(self, pool: ThreadPoolExecutor, fn, *, meta: dict) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._meta[job_id] = dict(meta)
            self._futures[job_id] = pool.submit(fn)
        return job_id

    def status(self, job_id: str) -> dict:
        with self._lock:
            future = self._futures.get(job_id)
            meta = self._meta.get(job_id, {})
        if future is None:
            return {"state": "not_found"}
        if not future.done():
            return {"state": "pending", "meta": meta}
        exc = future.exception()
        if exc is not None:
            return {"state": "failed", "meta": meta, "error": repr(exc)}
        snap = {"state": "done", "meta": meta}
        result = future.result()
        # Fetch jobs return a FetchResult; surface what actually happened so
        # the UI can distinguish "added 240 bars" from "sources unavailable,
        # added nothing". Duck-typed so this registry stays fetcher-agnostic.
        status = getattr(result, "status", None)
        bars_added = getattr(result, "bars_added", None)
        if status is not None and bars_added is not None:
            snap["result"] = {"status": status, "bars_added": bars_added}
        return snap
