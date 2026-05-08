"""Image preparation shared by multimodal provider clients."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

_DEFAULT_MODEL_IMAGE_MAX_DIM = 2048
_MIN_MODEL_IMAGE_MAX_DIM = 256


def model_image_max_dim() -> int:
    """Return the max width/height sent to provider vision APIs.

    Set ``FOCUSPARSE_MODEL_IMAGE_MAX_DIM=0`` to disable downscaling for a
    controlled experiment.
    """
    raw = os.environ.get("FOCUSPARSE_MODEL_IMAGE_MAX_DIM")
    if raw is None:
        return _DEFAULT_MODEL_IMAGE_MAX_DIM
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_MODEL_IMAGE_MAX_DIM
    if parsed <= 0:
        return 0
    return max(_MIN_MODEL_IMAGE_MAX_DIM, parsed)


def read_model_image_bytes(path: Path, *, max_dim: int | None = None) -> bytes:
    """Read an image, downscaling large rasters before provider upload."""
    data = Path(path).read_bytes()
    limit = model_image_max_dim() if max_dim is None else max_dim
    if limit <= 0:
        return data

    try:
        from PIL import Image

        with Image.open(BytesIO(data)) as img:
            if max(img.size) <= limit:
                return data
            img = img.convert("RGB")
            img.thumbnail((limit, limit), Image.Resampling.LANCZOS)
            out = BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
    except Exception:
        return data
