"""Retry transient provider failures around one model call."""

from __future__ import annotations

import asyncio
import errno
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from focusparse.models._timeouts import model_retry_attempts, model_retry_sleep_s

T = TypeVar("T")

logger = logging.getLogger(__name__)


async def retry_transient_model_call(
    provider: str,
    call: Callable[[], Awaitable[T]],
) -> T:
    """Retry one provider operation when the failure is likely infrastructural."""
    attempts = model_retry_attempts()
    sleep_s = model_retry_sleep_s()
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except Exception as exc:
            if attempt >= attempts or not is_transient_model_error(exc):
                raise
            logger.info(
                "Retrying %s model call after transient %s (%d/%d)",
                provider,
                type(exc).__name__,
                attempt,
                attempts,
            )
            if sleep_s:
                await asyncio.sleep(sleep_s)
                sleep_s *= 2
    raise AssertionError("unreachable retry loop exit")


def is_transient_model_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, OSError) and exc.errno in {
        errno.ECONNABORTED,
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.EHOSTUNREACH,
        errno.ENETDOWN,
        errno.ENETUNREACH,
        errno.ETIMEDOUT,
    }:
        return True
    name = type(exc).__name__.lower()
    module = type(exc).__module__.lower()
    message = str(exc).lower()
    if "auth" in name or "permission" in name:
        return False
    transient_markers = (
        "timeout",
        "timed out",
        "connection",
        "connect",
        "network is unreachable",
        "cannot connect",
        "nodename nor servname",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
    )
    return any(
        marker in name or marker in module or marker in message for marker in transient_markers
    )
