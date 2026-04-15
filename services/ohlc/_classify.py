"""Helpers for attaching FailureClassification to adapter exceptions.

Plan 18: adapters call `attach_classification(err, ...)` before re-raising
so CircuitBreaker.record_failure can read a typed signal instead of
sniffing exception internals.
"""

from __future__ import annotations

import time
from email.utils import parsedate_to_datetime

from services.ohlc.circuit_breaker import FailureClass, FailureClassification


def attach_classification(
    err: BaseException,
    *,
    failure_class: FailureClass,
    retry_after_seconds: int | None = None,
) -> BaseException:
    """Attach a FailureClassification to `err` and return it for re-raising."""
    err.ftl_failure = FailureClassification(  # type: ignore[attr-defined]
        failure_class=failure_class,
        retry_after_seconds=retry_after_seconds,
    )
    return err


def classify_http_error(err: BaseException) -> tuple[FailureClass, int | None]:
    """Map a `requests.HTTPError`-shaped exception to (class, retry_after_seconds).

    Accepts any object with a `.response` attribute exposing `.status_code`
    and `.headers`, so tests can use plain dataclasses without importing
    `requests`.
    """
    response = getattr(err, "response", None)
    if response is None:
        return "network", None
    code = getattr(response, "status_code", None)
    headers = getattr(response, "headers", {}) or {}
    retry_after: int | None = None
    header = headers.get("Retry-After") if hasattr(headers, "get") else None
    if header is not None:
        try:
            retry_after = int(header)
        except (TypeError, ValueError):
            try:
                dt = parsedate_to_datetime(header)
                retry_after = max(0, int(dt.timestamp() - time.time()))
            except (TypeError, ValueError):
                retry_after = None
    if code == 429:
        return "rate_limit", retry_after
    if code is not None and 500 <= code < 600:
        return "server_error", retry_after
    return "other", retry_after
