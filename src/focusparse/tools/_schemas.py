"""Shared Pydantic field helpers for tool input models.

`bbox_norm_field` is the canonical Pydantic Field for a normalized bounding
box. Pydantic emits `tuple[float, float, float, float]` as a heterogenous
`prefixItems` JSON schema that most agent prompt renderers can't introspect;
expressing it as `list[float]` with `min_length=4`/`max_length=4` plus a
descriptive Field gives a clean `array(items=number)` schema with a usable
`description` and `examples` block.

Used by `InspectRegionInput.bbox_norm` and `GetTextLayerInput.bbox_norm`
(via `tools.inspect_region` and `tools.get_text_layer`). The runtime path
keeps coercing tuple-typed bboxes upstream of these models, so existing call
sites that pass `tuple` literals stay working.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

_BBOX_NORM_DESCRIPTION = (
    "Normalized bounding box [x0, y0, x1, y1] in [0,1] space, top-left "
    "origin. (0,0) is the top-left of the page; (1,1) is the bottom-right. "
    "If you have a pixel-space bbox from layout_detect, convert via "
    "[x0/image_width, y0/image_height, x1/image_width, y1/image_height]."
)

_BBOX_NORM_EXAMPLE = [0.10, 0.20, 0.50, 0.60]


def bbox_norm_field(*, optional: bool = False) -> Any:
    """Return a Pydantic Field with the canonical bbox_norm metadata.

    Args:
        optional: When True, the field defaults to None and accepts None;
            used by `get_text_layer` where bbox is an optional filter.
    """
    if optional:
        return Field(
            default=None,
            description=_BBOX_NORM_DESCRIPTION + " Pass null to get the whole page.",
            examples=[_BBOX_NORM_EXAMPLE, None],
            min_length=4,
            max_length=4,
        )
    return Field(
        ...,
        description=_BBOX_NORM_DESCRIPTION,
        examples=[_BBOX_NORM_EXAMPLE],
        min_length=4,
        max_length=4,
    )
