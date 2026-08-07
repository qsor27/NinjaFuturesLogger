"""OHLC failure classification — the single source of truth.

Adapters attach a FailureClassification before re-raising
(attach_classification / classify_http_error); the circuit breaker and
the fetcher's forensic trail both classify caught exceptions via
classify_exception. Breaker behavior and the
fetch_source_attempts.error_class column can therefore never disagree.
"""

from __future__ import annotations

import time
from email.utils import parsedate_to_datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

FailureClass = Literal["rate_limit", "server_error", "network", "no_data", "other"]


class FailureClassification(BaseModel):
    """Optional structured failure signal attached to adapter exceptions.

    Adapters that know *why* a call failed (HTTP status code, explicit
    Retry-After header, connection error) should attach an instance of
    this model to the exception as an attribute named `ftl_failure`.
    classify_exception looks for that attribute and falls back to
    classifying from the exception shape if absent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    failure_class: FailureClass
    retry_after_seconds: int | None = None


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


def classify_exception(err: BaseException) -> tuple[FailureClass, int | None]:
    """Classify any exception raised by a source adapter.

    Precedence:
    1. An attached FailureClassification (adapters set this) wins.
    2. An HTTP-shaped error (non-None `.response`) is classified by status
       code + Retry-After header via classify_http_error.
    3. Anything else is "other" — counts toward the slow-trip threshold
       but never fast-trips the breaker.
    """
    attached = getattr(err, "ftl_failure", None)
    if isinstance(attached, FailureClassification):
        return attached.failure_class, attached.retry_after_seconds
    if getattr(err, "response", None) is None:
        return "other", None
    return classify_http_error(err)


def http_status(err: BaseException) -> int | None:
    """Extract an HTTP status code from a `requests.HTTPError`-shaped exception."""
    response = getattr(err, "response", None)
    code = getattr(response, "status_code", None)
    return int(code) if code is not None else None
