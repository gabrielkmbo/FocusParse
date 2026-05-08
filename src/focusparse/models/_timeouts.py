"""Shared model-call timeout configuration."""

from __future__ import annotations

import os

_DEFAULT_MODEL_TIMEOUT_S = 180.0
_MIN_MODEL_TIMEOUT_S = 1.0


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
