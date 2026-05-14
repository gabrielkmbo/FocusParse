"""Shared model-call timeout and retry configuration."""

from __future__ import annotations

import os

_DEFAULT_MODEL_TIMEOUT_S = 180.0
_MIN_MODEL_TIMEOUT_S = 1.0
_DEFAULT_MODEL_RETRY_ATTEMPTS = 2
_MIN_MODEL_RETRY_ATTEMPTS = 1
_MAX_MODEL_RETRY_ATTEMPTS = 5
_DEFAULT_MODEL_RETRY_SLEEP_S = 0.5


def model_timeout_s() -> float:
    """Return the wall-clock timeout for one provider model call."""
    raw = os.environ.get("FOCUSPARSE_MODEL_TIMEOUT_S")
    if not raw:
        return _DEFAULT_MODEL_TIMEOUT_S
    try:
        parsed = float(raw)
    except ValueError:
        return _DEFAULT_MODEL_TIMEOUT_S
    return max(_MIN_MODEL_TIMEOUT_S, parsed)


def model_retry_attempts() -> int:
    """Return total attempts for transient provider failures."""
    raw = os.environ.get("FOCUSPARSE_MODEL_RETRY_ATTEMPTS")
    if raw is None:
        raw = os.environ.get("FOCUSPARSE_MODEL_RETRIES")
    if not raw:
        return _DEFAULT_MODEL_RETRY_ATTEMPTS
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_MODEL_RETRY_ATTEMPTS
    return max(_MIN_MODEL_RETRY_ATTEMPTS, min(_MAX_MODEL_RETRY_ATTEMPTS, parsed))


def model_retry_sleep_s() -> float:
    """Return base sleep between transient provider retries."""
    raw = os.environ.get("FOCUSPARSE_MODEL_RETRY_SLEEP_S")
    if not raw:
        return _DEFAULT_MODEL_RETRY_SLEEP_S
    try:
        parsed = float(raw)
    except ValueError:
        return _DEFAULT_MODEL_RETRY_SLEEP_S
    return max(0.0, parsed)
