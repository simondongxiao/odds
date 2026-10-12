"""Bounded exponential-backoff wrapper with structured attempt evidence."""
from __future__ import annotations

import time
import re
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4
    delays: tuple[float, ...] = (2.0, 4.0, 8.0)
    retry_statuses: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)


class HTTPStatusError(RuntimeError):
    def __init__(self, status: int):
        self.code = int(status)
        super().__init__(f"HTTP_{status}")


def _exception_status(exc: Exception) -> int | None:
    status = getattr(exc, "code", None)
    if isinstance(status, int):
        return status
    match = re.search(r"\bHTTP[_ ](\d{3})\b", str(exc), re.I)
    return int(match.group(1)) if match else None


def request_with_retry(
    operation: Callable[[], Any],
    *,
    url: str,
    policy: RetryPolicy = RetryPolicy(),
    validate: Callable[[Any], bool] | None = None,
    status_of: Callable[[Any], int | None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[Any, list[dict[str, Any]]]:
    if policy.attempts < 1:
        raise ValueError("attempts must be >= 1")
    attempts: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for number in range(1, policy.attempts + 1):
        started = clock()
        try:
            value = operation()
            status = status_of(value) if status_of else None
            valid = validate(value) if validate else True
            if status is not None and not 200 <= int(status) < 400:
                raise HTTPStatusError(int(status))
            if not valid:
                raise ValueError("EMPTY_OR_INVALID_RESPONSE")
            attempts.append({"attempt": number, "url": url, "ok": True, "http_status": status,
                             "elapsed_ms": round((clock() - started) * 1000, 3), "sleep_before_next_seconds": 0})
            return value, attempts
        except Exception as exc:
            last_error = exc
            status = _exception_status(exc)
            # Permanent 4xx responses do not improve with waiting.  Network
            # exceptions, empty/invalid responses, 408/425/429 and configured
            # 5xx statuses remain retryable.
            retryable = status is None or status in policy.retry_statuses
            delay = (policy.delays[min(number - 1, len(policy.delays) - 1)]
                     if retryable and policy.delays and number < policy.attempts else 0)
            attempts.append({"attempt": number, "url": url, "ok": False, "http_status": status,
                             "error_type": type(exc).__name__, "error": str(exc),
                             "elapsed_ms": round((clock() - started) * 1000, 3),
                             "sleep_before_next_seconds": delay})
            if retryable and number < policy.attempts:
                sleeper(delay)
            else:
                setattr(exc, "retry_attempts", attempts)
                raise
    assert last_error is not None
    setattr(last_error, "retry_attempts", attempts)
    raise last_error
