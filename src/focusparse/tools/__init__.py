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

from pydantic import BaseModel, Field

# Submodule-shadowing avoidance: importing `get_text_layer` (the function)
# directly into this `__init__` namespace would overwrite the
# `focusparse.tools.get_text_layer` submodule attribute, breaking
# `import focusparse.tools.get_text_layer as mod` callers (the existing
# tests). Alias to underscore-prefixed names to keep the package's
# submodule attributes intact.
from focusparse.tools.get_text_layer import GetTextLayerInput, GetTextLayerOutput
from focusparse.tools.get_text_layer import get_text_layer as _get_text_layer
from focusparse.tools.inspect_region import InspectRegionInput, InspectRegionOutput
from focusparse.tools.inspect_region import inspect_region as _inspect_region
from focusparse.tools.layout_detect import LayoutDetectionOutput
from focusparse.tools.layout_detect import detect_layout as _detect_layout
from focusparse.tools.run_python import RunPythonInput, RunPythonOutput
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
    # Optional Pydantic output model rendered into the prompt's "Returns:"
    # section (Phase 2, 2026-05-04). Tools without a typed output stay
    # readable; the renderer just skips the Returns block for them.
    output_model: type[BaseModel] | None = None


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

    The underlying `detect_layout` function takes raw PNG bytes plus
    page + width/height metadata. Agents only need to provide the image
    path and the page number; we extract dimensions from the PNG header
    at the runner boundary.
    """

    image_path: str = Field(
        ...,
        description=(
            "Absolute path to the page PNG you want to analyze. Use one of "
            "the available_page_images strings supplied in the initial user "
            "turn — any other path will be rejected by the runner."
        ),
        examples=[
            "/Users/me/.cache/focusparse/hf_staging/data/processed/AN040_EN/images/AN040_EN_page_0003_300dpi.png"
        ],
    )
    page: int = Field(
        default=1,
        ge=1,
        description="1-indexed page number; echoed back in the response.",
    )
    confidence_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Drop boxes with score below this; 0.3 is the default.",
    )


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
    # Pull width/height from the PNG header so the agent doesn't have to
    # know them. PIL handles arbitrary PNG without loading the full pixel
    # buffer when we only call .size.
    from PIL import Image

    with Image.open(image_path) as im:
        image_width, image_height = im.size
    result = await _detect_layout(
        png_bytes,
        page=inp.page,
        image_width=image_width,
        image_height=image_height,
        endpoint_url=layout_endpoint_url,
        hf_token=hf_token,
        cache_dir=layout_cache_dir,
        confidence_threshold=inp.confidence_threshold,
    )
    # `detect_layout` returns a `LayoutDetectionOutput` with `.boxes`.
    # Surface a JSON-serializable summary the LLM can read back.
    boxes = [
        {
            "label": b.label,
            "bbox": list(b.bbox),
            "score": b.score,
            "figure_class": b.figure_class,
        }
        for b in (result.boxes or [])
    ]
    return {
        "page": inp.page,
        "image_width": image_width,
        "image_height": image_height,
        "n_regions": len(boxes),
        "regions": boxes[:8],
    }


def _summarize_layout_detect(out: dict[str, Any]) -> str:
    n = out.get("n_regions", 0)
    types = sorted({r.get("label") or "?" for r in out.get("regions") or []})
    page = out.get("page", "?")
    return f"page={page}, n_regions={n}, types={types}"


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
    paths = out.get("new_image_paths") or []
    n_new = len(out.get("new_image_refs") or paths)
    paths_part = f", new_paths={paths[:2]}" if paths else ""
    return f"stdout={stdout!r}, n_new_images={n_new}{paths_part}, exit_code={out.get('exit_code')}"


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
    output_model=InspectRegionOutput,
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
    output_model=GetTextLayerOutput,
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
    output_model=LayoutDetectionOutput,
)


RUN_PYTHON_SPEC = ToolSpec(
    name="run_python",
    description=(
        "Run sandboxed Python over previously-cropped images. "
        "Use for coding-driven zoom (LANCZOS upsample of tiny crops), "
        "peak detection on chart axes, or PIL-based annotation. "
        "Inside the sandbox: `images` is a dict keyed by the strings "
        "you passed as `image_refs`; values are PIL.Image objects. "
        "Call `save_image(img)` to return a new PNG (re-feedable as "
        "`image_refs` in a subsequent call). `print(...)` is captured "
        "into stdout. "
        "Allowlist: PIL, numpy, matplotlib, scipy, plus io/math/statistics/"
        "hashlib/json/base64/itertools/functools. Forbidden: os, subprocess, "
        "open(), exec(), eval(), socket. Wall-time cap is 15s by default."
    ),
    input_model=RunPythonInput,
    runner=_run_python_runner,
    summarize=_summarize_run_python,
    output_model=RunPythonOutput,
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


# ---------------------------------------------------------------------------
# 2026-05-04 Phase 2 — agent-prompt tool block renderer
# ---------------------------------------------------------------------------


# Per-tool chaining notes. The LLM sees these in the prompt's "Chains
# with:" section. Each note names the contract that's invisible from the
# bare schema (coordinate system mismatch, ref/path identity).
_CHAINS_WITH: dict[str, list[str]] = {
    "inspect_region": [
        (
            "Pre-feed: layout_detect's regions[i].bbox is in PIXELS — divide by "
            "image_width / image_height to produce bbox_norm before calling "
            "inspect_region."
        ),
        (
            "Post-feed: crop_ref (an absolute path) → run_python.image_refs[0] "
            "for upsample / draw / peak detection. The same string is the key "
            "in the sandbox's `images` dict."
        ),
    ],
    "get_text_layer": [
        (
            "Pre-feed: same pixel→norm conversion as inspect_region when chaining "
            "from layout_detect."
        ),
        (
            "Escalation: when source='empty_native' (scanned PDF), call "
            "inspect_region(mode='element') to OCR the same bbox."
        ),
    ],
    "layout_detect": [
        (
            "Post-feed: each regions[i].bbox is pixel-space — convert by dividing "
            "[x0, y0, x1, y1] by [image_width, image_height, image_width, "
            "image_height] before passing to inspect_region.bbox_norm or "
            "get_text_layer.bbox_norm."
        ),
        (
            "Pair with figure_class: when label='picture' and figure_class='bar_chart', "
            "follow up with run_python on inspect_region's crop for axis-tick reading."
        ),
    ],
    "run_python": [
        (
            "Pre-feed: pass an inspect_region.crop_ref (absolute path) directly as "
            "image_refs[0]; the sandbox keys `images[ref]` by the exact string you "
            "passed."
        ),
        (
            "Post-feed: each save_image(img) yields a 16-char ref in new_image_refs. "
            "Pass that ref back as image_refs in a subsequent run_python call to "
            "chain transformations."
        ),
    ],
}


# When-to-use notes for each tool. Concrete + use-case-driven so the LLM
# picks the right primitive instead of defaulting to inspect_region.
_WHEN_TO_USE: dict[str, list[str]] = {
    "inspect_region": [
        "Pull a specific region's text or visual.",
        "Get a usable PNG you can re-feed to run_python for zoom / transform.",
    ],
    "get_text_layer": [
        "Read native PDF text — deterministic and free.",
        "Filter to a specific bbox to extract a caption / footnote / table cell.",
        "Try this BEFORE inspect_region(mode='element') unless you know the PDF is scanned.",
    ],
    "layout_detect": [
        "Discover regions on a page when you don't yet know what's there.",
        "Identify chart vs table vs text before deciding which inspect_region mode to use.",
    ],
    "run_python": [
        "LANCZOS upsample tiny crops (axis labels, footnote text).",
        "Annotate / overlay onto a crop for human-readable answer evidence.",
        "Compute over chart pixels (peak detection, OCR confidence aggregation).",
    ],
}


# Worked example calls. Each is a JSON-shaped dict the LLM can copy. They
# are validated against the tool's input_model in tests/test_tool_block.py
# so a broken example fails the build, not the user.
_EXAMPLE_CALLS: dict[str, dict[str, Any]] = {
    "inspect_region": {
        "doc_path": "/Users/me/.cache/focusparse/pdfs/AN040_EN.pdf",
        "page": 3,
        "bbox_norm": [0.10, 0.20, 0.50, 0.60],
        "mode": "image",
    },
    "get_text_layer": {
        "doc_path": "/Users/me/.cache/focusparse/pdfs/AN040_EN.pdf",
        "page": 3,
        "bbox_norm": [0.10, 0.20, 0.50, 0.60],
    },
    "layout_detect": {
        "image_path": (
            "/Users/me/.cache/focusparse/hf_staging/data/processed/"
            "AN040_EN/images/AN040_EN_page_0003_300dpi.png"
        ),
        "page": 3,
        "confidence_threshold": 0.3,
    },
    "run_python": {
        "code": (
            "from PIL import Image\n"
            "ref = image_refs[0]\n"
            "img = images[ref]\n"
            "out = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)\n"
            "print('upsampled', img.size, '->', out.size)\n"
            "save_image(out)\n"
        ),
        "image_refs": ["/Users/me/cache/crops/abc123.png"],
    },
}


def format_agent_tool_block(
    tools: list[ToolSpec],
    *,
    mode: Literal["careful", "generic"] = "careful",
) -> str:
    """Render an agent-readable tool block for the system prompt.

    careful: full per-tool description + field schemas (descriptions +
        examples) + Returns block + When-to-use + Chains-with + worked
        example call. Used by ReActAgent and the future LLM-driven
        inspector.
    generic: name + description + field-name list only. Used by
        AgentBaseline; keeps the prompt thin since the comparator row's
        budget is tighter by design.
    """
    if mode == "generic":
        return _format_generic(tools)
    return _format_careful(tools)


def _format_generic(tools: list[ToolSpec]) -> str:
    lines = ["Available tools:"]
    for t in tools:
        schema = t.input_model.model_json_schema()
        props = schema.get("properties", {})
        names = ", ".join(list(props.keys())[:8])
        lines.append(f"- {t.name}({names})\n    {t.description}")
    return "\n".join(lines)


def _format_careful(tools: list[ToolSpec]) -> str:
    parts = ["Available tools:"]
    for t in tools:
        parts.append(_format_one_tool_careful(t))
    return "\n\n".join(parts)


def _format_one_tool_careful(spec: ToolSpec) -> str:
    lines = [f"### {spec.name}", "", spec.description, ""]

    # Inputs.
    lines.append("Inputs:")
    schema = spec.input_model.model_json_schema()
    required = set(schema.get("required") or [])
    properties = schema.get("properties") or {}
    defs = schema.get("$defs") or {}
    for name, prop in properties.items():
        lines.append(_format_field_line(name, prop, required=name in required, defs=defs))
    lines.append("")

    # Returns.
    if spec.output_model is not None:
        out_schema = spec.output_model.model_json_schema()
        out_props = out_schema.get("properties") or {}
        if out_props:
            lines.append("Returns:")
            for name, prop in out_props.items():
                desc = prop.get("description") or ""
                # Description-only line; keep it short and skip type/example
                # decoration to bound prompt growth.
                if desc:
                    lines.append(f"  {name} — {desc}")
                else:
                    lines.append(f"  {name}")
            lines.append("")

    # When to use.
    when = _WHEN_TO_USE.get(spec.name)
    if when:
        lines.append("When to use:")
        for w in when:
            lines.append(f"  - {w}")
        lines.append("")

    # Chains with.
    chains = _CHAINS_WITH.get(spec.name)
    if chains:
        lines.append("Chains with:")
        for c in chains:
            lines.append(f"  - {c}")
        lines.append("")

    # Example call.
    example = _EXAMPLE_CALLS.get(spec.name)
    if example is not None:
        import json as _json

        body = _json.dumps({"action": spec.name, "action_input": example}, indent=2)
        lines.append("Example call:")
        for ln in body.splitlines():
            lines.append(f"  {ln}")

    return "\n".join(lines).rstrip()


def _format_field_line(
    name: str,
    prop: dict[str, Any],
    *,
    required: bool,
    defs: dict[str, Any],
) -> str:
    """One-line field render: name (type, required/default) — description; example: ..."""
    type_str = _render_type(prop, defs=defs)
    if required:
        req_str = "required"
    elif "default" in prop:
        # Pydantic only emits the `default` key for fixed defaults; fields with
        # `default_factory=list` etc. are absent here, which we render as
        # "optional" rather than the misleading literal string "none".
        req_str = f"default={prop['default']!r}"
    else:
        req_str = "optional"
    desc = prop.get("description") or ""
    line = f"  {name} ({type_str}, {req_str})"
    if desc:
        line += f" — {desc}"
    examples = prop.get("examples")
    if examples:
        first = examples[0]
        line += f"\n      example: {first!r}"
    return line


def _render_type(prop: dict[str, Any], *, defs: dict[str, Any]) -> str:
    """Render a JSON-Schema property type for the prompt.

    Special-cases:
      - array(minItems=4, maxItems=4, items=number) -> "array of 4 numbers"
      - enum -> "one of: a, b, c"
      - $ref -> chase into $defs and recurse.
    """
    if "$ref" in prop:
        ref = prop["$ref"].split("/")[-1]
        target = defs.get(ref)
        if target:
            return _render_type(target, defs=defs)
        return ref

    if "anyOf" in prop:
        # Collapse `T | None` to `T (nullable)`.
        non_null = [p for p in prop["anyOf"] if p.get("type") != "null"]
        nullable = len(non_null) != len(prop["anyOf"])
        if len(non_null) == 1:
            inner = _render_type(non_null[0], defs=defs)
            return f"{inner} (nullable)" if nullable else inner
        return " | ".join(_render_type(p, defs=defs) for p in prop["anyOf"])

    if "enum" in prop:
        return "one of: " + ", ".join(repr(v) for v in prop["enum"])

    typ = prop.get("type", "?")
    if typ == "array":
        min_i = prop.get("minItems")
        max_i = prop.get("maxItems")
        items = prop.get("items") or {}
        items_type = items.get("type", "?")
        if min_i and min_i == max_i:
            return f"array of {min_i} {items_type}s"
        return f"array of {items_type}"
    if typ == "integer":
        bounds = []
        if "minimum" in prop:
            bounds.append(f"≥{prop['minimum']}")
        if "maximum" in prop:
            bounds.append(f"≤{prop['maximum']}")
        suffix = f" ({', '.join(bounds)})" if bounds else ""
        return f"integer{suffix}"
    return typ
