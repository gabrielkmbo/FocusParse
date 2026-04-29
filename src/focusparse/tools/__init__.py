"""FunctionTool-wrapped primitives.

Minimal, strong tool set (per plan §3):
  - inspect_region (3 modes: image / element / region)
  - expand_context — a workflow stage (FocusParse-specific); not exposed
    to comparator agents
  - get_text_layer
  - chart_to_table (optional)
  - run_python (sandboxed, for coding-driven zoom)
  - layout_detect

This module also exposes the **agent-callable tool registry** consumed
by the ReAct loop and Agent baseline (`src/focusparse/pipeline/
react_agent.py` and `src/focusparse/pipeline/agent_baseline.py`). The
registry maps tool names → (description, input schema, async callable)
so a generic agent can dispatch by name. FocusParse's pipeline doesn't
go through this registry — it calls the underlying functions directly
through its stage machine — but the tool *count* axis (`--tool-set
minimal | full`) is mirrored across all method types via `resolve_tool_set`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

# Submodule-shadowing avoidance: importing `get_text_layer` (the function)
# directly into this `__init__` namespace would overwrite the
# `focusparse.tools.get_text_layer` submodule attribute, breaking
# `import focusparse.tools.get_text_layer as mod` callers (the existing
# tests). Alias to underscore-prefixed names to keep the package's
# submodule attributes intact.
from focusparse.tools.get_text_layer import GetTextLayerInput
from focusparse.tools.get_text_layer import get_text_layer as _get_text_layer
from focusparse.tools.inspect_region import InspectRegionInput
from focusparse.tools.inspect_region import inspect_region as _inspect_region
from focusparse.tools.layout_detect import detect_layout as _detect_layout
from focusparse.tools.run_python import RunPythonInput
from focusparse.tools.run_python import run_python as _run_python


@dataclass
class ToolSpec:
    """Agent-callable tool description.

    `runner` is an async callable that takes the parsed-and-validated
    input model + a context dict (cache dirs, pdf path, etc.) and returns
    a JSON-serializable result the agent can read back as the next
    observation.

    The agent prompt lists `name + description + schema_json` so the LLM
    knows what the tool does and what fields to fill. The loop calls
    `spec.runner(input_model, **context)` and feeds `spec.summarize(out)`
    back as the next observation.
    """

    name: str
    description: str
    input_model: type[BaseModel]
    runner: Callable[..., Awaitable[Any]]
    # Compress a tool output to a short text summary the LLM can read
    # back. Default: `repr()`. Tools with long outputs (crop refs,
    # layout boxes) override this with a one-paragraph rendering.
    summarize: Callable[[Any], str] = repr


# ---------------------------------------------------------------------------
# Tool wrappers — adapt the primitive functions to the agent registry shape
# ---------------------------------------------------------------------------


async def _inspect_region_runner(
    inp: InspectRegionInput,
    *,
    cache_dir: Path | None = None,
    layout_endpoint_url: str | None = None,
    hf_token: str | None = None,
    layout_cache_dir: Path | None = None,
    **_unused: Any,
) -> dict[str, Any]:
    out = await _inspect_region(
        inp,
        cache_dir=cache_dir,
        layout_endpoint_url=layout_endpoint_url,
        hf_token=hf_token,
        layout_cache_dir=layout_cache_dir,
    )
    return out.model_dump()


def _summarize_inspect_region(out: dict[str, Any]) -> str:
    crop = out.get("crop_ref", "?")
    ocr = out.get("ocr_text") or ""
    if ocr:
        ocr = ocr.strip().replace("\n", " ")[:200]
    sub_n = len(out.get("sub_regions") or [])
    parts = [f"crop={crop}"]
    if ocr:
        parts.append(f"ocr={ocr!r}")
    if sub_n:
        parts.append(f"n_sub_regions={sub_n}")
    return ", ".join(parts)


async def _get_text_layer_runner(
    inp: GetTextLayerInput,
    *,
    cache_dir: Path | None = None,
    text_layer_cache_dir: Path | None = None,
    **_unused: Any,
) -> dict[str, Any]:
    # Caller may supply either `cache_dir` (legacy) or `text_layer_cache_dir`.
    out = await _get_text_layer(inp, cache_dir=text_layer_cache_dir or cache_dir)
    return out.model_dump()


def _summarize_get_text_layer(out: dict[str, Any]) -> str:
    text = (out.get("text") or "").strip().replace("\n", " ")[:300]
    source = out.get("source", "?")
    n_spans = len(out.get("spans") or [])
    return f"text={text!r}, source={source}, n_spans={n_spans}"


class _LayoutDetectInput(BaseModel):
    """Adapter input for the layout_detect tool.

    The underlying `detect_layout` function takes raw PNG bytes; agents
    pass an image path, which we read at the runner boundary.
    """

    image_path: str
    confidence_threshold: float = 0.3


async def _layout_detect_runner(
    inp: _LayoutDetectInput,
    *,
    layout_endpoint_url: str | None = None,
    hf_token: str | None = None,
    layout_cache_dir: Path | None = None,
    **_unused: Any,
) -> dict[str, Any]:
    image_path = Path(inp.image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    png_bytes = image_path.read_bytes()
    result = await _detect_layout(
        png_bytes,
        endpoint_url=layout_endpoint_url,
        hf_token=hf_token,
        cache_dir=layout_cache_dir,
        confidence_threshold=inp.confidence_threshold,
    )
    # `detect_layout` returns a list of dicts; surface the count + first 8.
    return {"n_regions": len(result), "regions": result[:8]}


def _summarize_layout_detect(out: dict[str, Any]) -> str:
    n = out.get("n_regions", 0)
    types = sorted(
        {r.get("label") or r.get("region_type") or "?" for r in out.get("regions") or []}
    )
    return f"n_regions={n}, types={types}"


async def _run_python_runner(
    inp: RunPythonInput,
    *,
    image_cache_dir: Path | None = None,
    crop_cache_dir: Path | None = None,
    **_unused: Any,
) -> dict[str, Any]:
    # Caller may pass either `image_cache_dir` or `crop_cache_dir` (the
    # inspector uses the latter naming).
    cache_root = image_cache_dir or crop_cache_dir
    out = await _run_python(
        inp,
        image_cache_dir=cache_root,
        new_image_cache_dir=cache_root,
    )
    return out.model_dump()


def _summarize_run_python(out: dict[str, Any]) -> str:
    stdout = (out.get("stdout") or "").strip().replace("\n", " ")[:300]
    n_new = len(out.get("new_image_refs") or [])
    return f"stdout={stdout!r}, n_new_images={n_new}, exit_code={out.get('exit_code')}"


# ---------------------------------------------------------------------------
# Specs + registry
# ---------------------------------------------------------------------------


INSPECT_REGION_SPEC = ToolSpec(
    name="inspect_region",
    description=(
        "Crop a rectangular region from a PDF page and optionally OCR it. "
        "Use to read fine details from a specific bbox. mode='image' returns "
        "just the crop; mode='element' adds Tesseract OCR; mode='region' "
        "additionally re-runs layout detection on the crop for sub-elements."
    ),
    input_model=InspectRegionInput,
    runner=_inspect_region_runner,
    summarize=_summarize_inspect_region,
)


GET_TEXT_LAYER_SPEC = ToolSpec(
    name="get_text_layer",
    description=(
        "Return the native PDF text on a given page (no OCR). Optionally "
        "filter to spans whose centroid lies inside `bbox_norm`. Use this "
        "before resorting to OCR — it's deterministic and free."
    ),
    input_model=GetTextLayerInput,
    runner=_get_text_layer_runner,
    summarize=_summarize_get_text_layer,
)


LAYOUT_DETECT_SPEC = ToolSpec(
    name="layout_detect",
    description=(
        "Return layout regions (text / picture / chart / table / caption / "
        "section_header / footnote etc.) for a given page image. Use to "
        "discover regions on a page when you don't yet know what's there."
    ),
    input_model=_LayoutDetectInput,
    runner=_layout_detect_runner,
    summarize=_summarize_layout_detect,
)


RUN_PYTHON_SPEC = ToolSpec(
    name="run_python",
    description=(
        "Run sandboxed Python over previously-cropped images for "
        "coding-driven zoom (e.g. LANCZOS upsample, peak detection). "
        "Allowlist: PIL, numpy, matplotlib, scipy. Pass `image_refs` "
        "(content-addressed crop ids from prior tool calls); the sandbox "
        "exposes them as `images: dict[ref, PIL.Image]` and `save_image(img)` "
        "for outputs."
    ),
    input_model=RunPythonInput,
    runner=_run_python_runner,
    summarize=_summarize_run_python,
)


_MINIMAL_TOOLS: tuple[ToolSpec, ...] = (INSPECT_REGION_SPEC, GET_TEXT_LAYER_SPEC)
_FULL_TOOLS: tuple[ToolSpec, ...] = (
    INSPECT_REGION_SPEC,
    GET_TEXT_LAYER_SPEC,
    LAYOUT_DETECT_SPEC,
    RUN_PYTHON_SPEC,
)


def resolve_tool_set(name: Literal["minimal", "full"]) -> list[ToolSpec]:
    """Return the ordered tool list for a given `--tool-set` name.

    minimal = inspect_region + get_text_layer  (universal "see-and-read"
    pair every method gets to see, including the ReAct loop).
    full    = + layout_detect + run_python     (lets the agent discover
    new regions and run coding-driven zoom).

    Note: this is the COMPARATOR-AGENT view of "+4 tools". FocusParse's
    own pipeline interprets `tool_set=full` as "expand_context stage runs
    + auto_zoom respects its flag" — same conceptual axis, different
    surface because the FocusParse pipeline calls these primitives
    through its stage machine rather than through the registry.
    """
    if name == "minimal":
        return list(_MINIMAL_TOOLS)
    if name == "full":
        return list(_FULL_TOOLS)
    raise ValueError(f"Unknown tool set: {name!r}")
