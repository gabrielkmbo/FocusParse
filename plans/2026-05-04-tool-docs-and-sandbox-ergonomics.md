# Tool docs + sandbox ergonomics — make detection / inspection / run_python LLM-usable

## Overview

Tighten the tool-surface so an LLM (the comparator ReAct today; the future
LLM-driven inspector tomorrow) can actually use detection (`layout_detect`),
inspection (`inspect_region`, `get_text_layer`), and the sandboxed coding
zoom (`run_python`) without prior knowledge of internal contracts. Three
changes: per-field Pydantic descriptions + examples; a new agent-prompt
renderer that includes worked examples and tool-chaining notes; and
`run_python` ergonomic fixes so its inputs accept what `inspect_region`
produces and its outputs are directly inspectable again.

This is the **prerequisite for Step 4 of the user's recommended Phase 6
sequence** (LLM-driven inspector dispatch). It also sharpens the comparator
ReAct row by removing the "schemas were unreadable" confound — a fairer
comparator hygiene pass than the C3 path-enumeration alone.

## Current State Analysis

### What an LLM currently sees in the system prompt

`react_agent._tool_block` (`src/focusparse/pipeline/react_agent.py:269-282`)
renders each `ToolSpec` in one line:

```
Available tools:
- inspect_region(doc_path: string, page: integer, bbox_norm: ?, mode: string, dpi: integer, ...)
    Crop a rectangular region from a PDF page and optionally OCR it. ...
- layout_detect(image_path: string, page: integer, confidence_threshold: number)
    Return layout regions ...
- run_python(code: string, image_refs: array, wall_time_s: integer)
    Run sandboxed Python over previously-cropped images for coding-driven zoom ...
```

That's all. No examples, no return-shape, no tool-chaining contract.

### Concrete failure modes this causes

1. **`bbox_norm` renders as `?`.** Pydantic's JSON Schema for `tuple[float,
float, float, float]` uses `prefixItems`/`array`; the renderer's
   `v.get('type', '?')` lookup misses it. The model gets no clue that the
   field wants 4 floats in [0,1]. Same for `get_text_layer.bbox_norm`.

2. **Pixel-vs-normalized coordinate mismatch is silent.** `layout_detect`
   returns `regions[i].bbox` in **absolute pixels** (`src/focusparse/tools/
layout_detect.py:39-43`). `inspect_region` requires **normalized [0,1]**
   in `bbox_norm` (`src/focusparse/tools/inspect_region.py:201-204` raises
   on `bbox_norm > 1.0`). Nothing in either schema or description says
   "divide by `image_width`/`image_height`." A model chaining
   `layout_detect → inspect_region` naïvely will hit
   `validation_error: bbox_norm must be a non-empty [0,1] rectangle`.

3. **Crop-ref vs. cache-key mismatch in `run_python`.**
   - `inspect_region` returns `crop_ref` = absolute path to
     `<cache_dir>/<crop_sha>.png`.
   - `run_python.image_refs` accepts both content-addressed refs (16-char
     stems) AND absolute paths (`run_python.py:117-130` resolver tries
     both). Working but undocumented.
   - `run_python.new_image_refs` returns 16-char sha256 stems, NOT paths.
     The agent has to know to construct `<cache_dir>/<ref>.png` to feed
     them back into another tool. The deterministic inspector's
     `_zoom_crop` does this with internal knowledge
     (`src/focusparse/pipeline/inspector.py:355-357`); an LLM cannot.

4. **Sandbox runtime API is undocumented at the call site.** The
   `RUN_PYTHON_SPEC.description` mentions `images: dict[ref, PIL.Image]`
   and `save_image(img)` but doesn't show:
   - `images` keys are exactly the strings passed in `image_refs`.
   - `print(...)` is captured into `RunPythonOutput.stdout` (line 251 in
     `run_python.py`).
   - `save_image(img)` appends to a buffer that becomes
     `RunPythonOutput.new_image_refs`.
   - `__import__` is gated by an allowlist; trying `import os` raises
     `ImportError("Sandbox: import of 'os' is not allowed")` — useful
     diagnostic, never shown to the model.
   - The exact 5-line code template (open from `images`, transform,
     `save_image`).

5. **No "Returns" section anywhere.** The output Pydantic models
   (`InspectRegionOutput`, `LayoutDetectionOutput`, `GetTextLayerOutput`,
   `RunPythonOutput`) carry rich shape info. None of it surfaces to the
   agent prompt. The agent has to guess what a tool returns.

### What's already in the right shape

- Per-tool `summarize` callables (`src/focusparse/tools/__init__.py:95`,
  121, 191, 216) already produce sensible one-line summaries the loop
  feeds back as the next observation. We don't change these.
- `ToolSpec` is the right abstraction; it just needs more fields surfaced.
- Sandbox security model (subprocess + rlimits + import allowlist + builtin
  allowlist) is solid; we don't change it. We only document it.

## Desired End State

After this plan:

1. Every tool input model has per-field `description=` and `examples=`
   set, including a JSON-Schema-friendly representation of `bbox_norm`
   (4-element `array` with `minItems=4, maxItems=4, items=number`,
   description = "[x0, y0, x1, y1] normalized to [0,1]").
2. The agent system-prompt includes per-tool blocks with: description,
   field schemas (with descriptions and examples), a "Returns" block from
   the output model, a "When to use / Chains with" block, and one worked
   example call. Built by a new `format_agent_tool_block(tools)` that
   ReActAgent + AgentBaseline + (future) LLM-driven inspector all use.
3. `run_python`:
   - `RunPythonOutput` gains a `new_image_paths: list[str]` field (absolute
     paths) computed alongside `new_image_refs` so the agent doesn't need
     to know about cache-dir layout.
   - `run_python_runner` (the agent-facing wrapper) accepts crop_ref-style
     absolute paths in `image_refs` transparently and emits them in
     `new_image_paths`.
   - The `RUN_PYTHON_SPEC.description` carries a complete worked example
     (read `images[ref]`, transform with PIL, `save_image`,
     `print` debug) and the allowlist explicitly named.
4. New tests cover: schema rendering for each tool, prompt-block content
   shape, run_python path round-trip, and an integration smoke that runs
   `layout_detect → inspect_region → run_python` against a fixture PDF
   with a real LLM-style mock.

### Verification (one-line each)

- `uv run pytest tests/test_tool_block.py tests/test_tools.py tests/test_run_python.py -v` passes.
- `uv run pytest` total stays green (current 525 + new tests).
- `uv run python scripts/dump_agent_prompt.py` (new tiny script) prints
  the rendered tool block and includes the strings "Returns:", "Chains
  with:", "Example:", and a `bbox_norm: [x0, y0, x1, y1]` four-float
  shape for every tool that takes one.
- A manual smoke against one fixture trace (using the trace viewer from
  the prior sub-plan) shows the agent's first user turn contains valid
  per-tool examples that match the runtime schema.

## What We're NOT Doing

- **No new tools.** `chart_to_table`, `expand_context-as-tool`, etc. are
  out of scope. We ship the 4 existing tools with better docs.
- **No sandbox security changes.** Same allowlist, same rlimits, same
  subprocess model. If the docstring claims a feature exists, it
  matches the existing implementation; we do not loosen anything.
- **No LLM-driven inspector.** This plan is the prerequisite, not the
  implementation. The LLM-driven inspector lands in a separate sub-plan
  that consumes the new tool-block renderer.
- **No A/B re-run** of the headline table. Tool docs land independently;
  the next person to run a comparator A/B picks them up automatically.
  The decision on whether to re-run ReAct stays with the user.
- **No changes to `summarize` callables.** The one-line observation
  rendered back to the agent stays identical so cached behaviors don't
  shift unexpectedly.
- **No changes to `run_python`'s sandbox boundary.** We do not add new
  modules to the import allowlist, do not relax builtins, do not raise
  rlimits.
- **No deprecation of `new_image_refs`.** It stays for back-compat with
  the deterministic `_zoom_crop`. We add `new_image_paths` alongside.

## Implementation Approach

Three phases. Each ships independently as a small commit set per
`feedback_commit_granularity`. Each ends green test-wise so a partial
landing never breaks the suite.

- **Phase 1** — Pydantic field-level descriptions + examples + JSON-schema
  fix for `bbox_norm`. Pure type/metadata change. No behavior change.
- **Phase 2** — `format_agent_tool_block` renderer. Replaces the
  one-liner; ReActAgent + AgentBaseline switch to it. New helper script
  `scripts/dump_agent_prompt.py` for inspection.
- **Phase 3** — `run_python` ergonomics: `new_image_paths` field +
  description-level worked example + agent-runner that surfaces paths
  transparently.

A short Phase 4 follows for an integration smoke test that exercises the
full chain end-to-end with a real fixture PDF and a scripted-mock LLM.

---

## Phase 1: Pydantic field-level descriptions + examples

### Overview

Touch each tool's input/output Pydantic models. Add `Field(...,
description=, examples=)` to every field. Special-case the `bbox_norm`
tuple so its JSON Schema is array-of-4-floats with a usable description,
not a `prefixItems` shape that the prompt renderer can't introspect.

This is a metadata-only change; runtime behavior is unchanged.

### Changes Required

#### 1. `src/focusparse/tools/_schemas.py` (new)

A small shared module that exports:

```python
def bbox_norm_field() -> Any:
    """Return a Pydantic Field with the canonical bbox_norm metadata.

    Pydantic emits `tuple[float, float, float, float]` as a heterogenous
    `prefixItems` JSON schema, which most agent prompts can't read.
    Reusing this Field across input models gives one consistent surface:
    a 4-element `array` with `description` + `examples` set so the
    rendered tool block always shows the same human-readable shape.
    """
    return Field(
        ...,
        description=(
            "Normalized bounding box [x0, y0, x1, y1] in [0,1] space, "
            "top-left origin. (0,0) is the top-left of the page; (1,1) "
            "is the bottom-right."
        ),
        examples=[[0.10, 0.20, 0.50, 0.60]],
        min_length=4,
        max_length=4,
    )
```

Use `list[float]` instead of `tuple[float, float, float, float]` in input
models so `min_length` / `max_length` apply via `conlist` shape; downstream
code that already coerces via `tuple(...)` keeps working.

#### 2. `src/focusparse/tools/inspect_region.py`

Update `InspectRegionInput`:

```python
class InspectRegionInput(BaseModel):
    doc_path: str = Field(
        ...,
        description="Absolute path to the source PDF on disk.",
        examples=["/Users/me/.cache/focusparse/pdfs/AN040_EN.pdf"],
    )
    page: int = Field(
        ...,
        ge=1,
        description="1-indexed page number.",
        examples=[3],
    )
    bbox_norm: list[float] = bbox_norm_field()
    mode: Literal["image", "element", "region"] = Field(
        default="element",
        description=(
            "image=crop only (cheapest, no OCR). element=crop+Tesseract "
            "OCR (use when you know the region is text-bearing). "
            "region=crop+sub-layout detection+per-sub-region OCR (use "
            "for mixed structures: chart+legend+caption, table+notes)."
        ),
        examples=["element", "image", "region"],
    )
    dpi: int = Field(
        default=300,
        ge=72,
        le=600,
        description="Render DPI; 300 is the default and matches gold.",
    )
    rotation: int = Field(
        default=0,
        description="Page rotation in degrees (0/90/180/270).",
    )
    expansion: Literal["none", "default", "aggressive"] = Field(
        default="default",
        description=(
            "Pad the crop bbox before slicing. "
            "default=2% on each side, aggressive=5%, none=tight."
        ),
    )
```

Update `InspectRegionOutput` with field descriptions (especially
`crop_ref`'s contract: "absolute path to a cached PNG; pass to
`run_python.image_refs` directly to manipulate via Python").

#### 3. `src/focusparse/tools/layout_detect.py`

Field descriptions on `DetectedBox` clarifying that `bbox` is in **absolute
pixels** (with description = "absolute pixel coordinates [x0, y0, x1,
y1]; divide each by image_width/image_height to convert to bbox_norm
for inspect_region"). Field descriptions on `LayoutDetectionOutput`.

#### 4. `src/focusparse/tools/get_text_layer.py`

Field descriptions on `GetTextLayerInput` (bbox_norm reused via shared
helper). Field descriptions on `GetTextLayerOutput.source` clarifying the
two values (`"native"` vs `"empty_native"`).

#### 5. `src/focusparse/tools/run_python.py`

Field descriptions on `RunPythonInput`:

```python
class RunPythonInput(BaseModel):
    code: str = Field(
        ...,
        description=(
            "Python source. The sandbox exposes `images: dict[str, "
            "PIL.Image]` keyed by the strings you pass in `image_refs`, "
            "and `save_image(img)` to return new PNGs. `print` output "
            "is captured into stdout."
        ),
        examples=[
            "from PIL import Image\n"
            "img = images[image_refs[0]]\n"
            "out = img.resize((img.width * 2, img.height * 2), "
            "Image.Resampling.LANCZOS)\n"
            "print('upsampled', img.size, '->', out.size)\n"
            "save_image(out)\n"
        ],
    )
    image_refs: list[str] = Field(
        default_factory=list,
        description=(
            "Refs to images to expose inside the sandbox. Accepts either "
            "16-char content-addressed cache stems (from a prior "
            "run_python's `new_image_refs`) OR absolute paths (e.g. an "
            "`inspect_region.crop_ref`)."
        ),
        examples=[["/path/to/abc123.png"]],
    )
    wall_time_s: int = Field(
        default=DEFAULT_WALL_TIME_S,
        ge=1,
        le=60,
        description="Wall-time budget in seconds; sandbox is killed past this.",
    )
```

Field descriptions on `RunPythonOutput`. (`new_image_paths` is added in
Phase 3 — Phase 1 just documents the existing fields.)

#### 6. Adjust the `_LayoutDetectInput` adapter

`src/focusparse/tools/__init__.py:128` — same field-level treatment.
`image_path` description: "Absolute path to the page PNG you want to
analyze. Use one of the available_page_images strings supplied in the
initial user turn." `confidence_threshold` description: "Drop boxes with
score below this; 0.3 is the default."

#### 7. Tests

**File**: `tests/test_tools.py` (extend)

- For each tool input model, `model_json_schema()` contains every field
  with a non-empty `description`.
- `bbox_norm` JSON schema is `{type: array, minItems: 4, maxItems: 4,
items: {type: number}}` with a `description` mentioning "[x0, y0,
  x1, y1]".
- `examples` are present on every field that has user-facing semantics.

**File**: `tests/test_inspect_region.py` (extend) / `tests/test_layout_detect.py` (extend) / `tests/test_run_python.py` (extend)

- Sanity assertion that the new `description=` strings round-trip through `model_validate(...)` and don't break parsing.

### Success Criteria

#### Automated:

- [ ] `uv run pytest tests/test_tools.py tests/test_inspect_region.py tests/test_layout_detect.py tests/test_get_text_layer.py tests/test_run_python.py -q` passes.
- [ ] `uv run pytest` total stays at ≥525 (no regressions; ~6 new tests added).
- [ ] `uv run ruff check src/focusparse/tools/` passes.
- [ ] Round-trip test: `InspectRegionInput.model_validate({"doc_path":"x.pdf","page":1,"bbox_norm":[0.1,0.2,0.3,0.4]})` succeeds; passing a list of length 3 raises a clear validation error mentioning "min_length=4".

#### Manual:

- [ ] Inspect `model_json_schema()` of each input model in a Python REPL and confirm every field has a `description`.
- [ ] Confirm the JSON schema for `bbox_norm` reads cleanly as a 4-element array with a description, not a heterogenous `prefixItems` tuple.

**Phase 1 commits:** ~6 small commits (one per file: `_schemas.py` new module → 4 input-model touches → 1 test extension), per granularity preference.

---

## Phase 2: `format_agent_tool_block` renderer + ReAct/AgentBaseline switch

### Overview

Replace `react_agent._tool_block`'s one-line dump with a new shared
`focusparse.tools.format_agent_tool_block(tools, *, mode)` that renders
each tool with: description, field schemas (description + example), a
"Returns" block built from the output Pydantic model, a "When to use /
Chains with" block, and one worked example call. Mode switch lets the
generic AgentBaseline keep its terser prompt.

### Changes Required

#### 1. New `format_agent_tool_block` in `src/focusparse/tools/__init__.py`

Lives next to `resolve_tool_set`. Two render modes:

```python
def format_agent_tool_block(
    tools: list[ToolSpec],
    *,
    mode: Literal["careful", "generic"] = "careful",
) -> str:
    """Render the agent-callable tools as a system-prompt block.

    careful: full schemas + examples + chaining notes (default for ReAct).
    generic: name + description + field names only (AgentBaseline).
    """
```

The careful mode for one tool:

```
### inspect_region

Crop a rectangular region from a PDF page and optionally OCR it. Use to
read fine details from a specific bbox.

Inputs:
  doc_path (string, required) — Absolute path to the source PDF.
                              example: /Users/.../AN040_EN.pdf
  page (integer ≥ 1, required) — 1-indexed page number.
                              example: 3
  bbox_norm (array of 4 numbers, required) — Normalized bounding box
    [x0, y0, x1, y1] in [0,1] space, top-left origin.
                              example: [0.10, 0.20, 0.50, 0.60]
  mode (one of: image, element, region; default=element) — image=crop
    only (cheapest). element=crop+OCR. region=crop+sub-layout+OCR.

Returns: { crop_ref, ocr_text, sub_regions, confidence, page_width_px,
  page_height_px }
  crop_ref — absolute path to the cached PNG. Pass directly to
             run_python.image_refs to manipulate via Python.
  ocr_text — Tesseract OCR output (null in image mode or when tesseract
             is missing).

When to use:
  - Pull a specific region's text or visual.
  - Get a usable PNG you can re-feed to run_python for zoom/transform.

Chains with:
  - Pre-feed: layout_detect's regions[i].bbox is in PIXELS — divide by
    image_width / image_height to produce bbox_norm before calling
    inspect_region.
  - Post-feed: crop_ref → run_python.image_refs[0] for upsample / draw.

Example call:
  {"action": "inspect_region",
   "action_input": {"doc_path": "/cache/foo.pdf", "page": 3,
                    "bbox_norm": [0.1, 0.2, 0.5, 0.6], "mode": "image"}}
```

Generic mode collapses Returns / When-to-use / Chains-with to skip
keep-prompt-short for AgentBaseline.

Build via:

- `_render_field(field_info: FieldInfo)` — name, type, default, description, example.
- `_render_returns(output_model: type[BaseModel] | None)` — walk
  `model_json_schema()`. Each `ToolSpec` gains an optional
  `output_model` field; if set, render its top-level fields.
- `_render_chains(spec: ToolSpec)` — pulled from a static dict in
  `__init__.py` keyed on `spec.name`. Edges:
  - `inspect_region` ← from `layout_detect` (with the pixel→norm conversion); → to `run_python`.
  - `layout_detect` → to `inspect_region` (with the pixel→norm conversion).
  - `get_text_layer` ← from `layout_detect` (same conversion); → no obvious downstream.
  - `run_python` ← from `inspect_region` (`crop_ref`); → output `new_image_paths` is itself a valid `image_refs` for re-feed.

#### 2. Add `output_model` to `ToolSpec` (optional)

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    runner: Callable[..., Awaitable[Any]]
    summarize: Callable[[Any], str] = repr
    output_model: type[BaseModel] | None = None  # NEW — rendered into "Returns"
```

Wire `output_model=InspectRegionOutput`, `LayoutDetectionOutput`,
`GetTextLayerOutput`, `RunPythonOutput` at each spec's construction.

#### 3. Switch `react_agent._tool_block` to use the new renderer

`src/focusparse/pipeline/react_agent.py:269-283` — replace with:

```python
from focusparse.tools import format_agent_tool_block

def _tool_block(tools: list[ToolSpec]) -> str:
    return format_agent_tool_block(tools, mode="careful")
```

Or remove `_tool_block` entirely and call the new renderer directly from
`_REACT_SYSTEM_PROMPT + "\n\n" + format_agent_tool_block(self.tools)`.

`src/focusparse/pipeline/agent_baseline.py:74` (in `_system_prompt`) —
switch from `_tool_block(self.tools)` to
`format_agent_tool_block(self.tools, mode="generic")`. The generic prompt
stays terser by design (per the active plan's "comparator differences"
note), but still gets correct schema rendering instead of `?` for
`bbox_norm`.

#### 4. New helper script `scripts/dump_agent_prompt.py`

Quick CLI that prints the rendered tool block to stdout:

```
uv run python scripts/dump_agent_prompt.py --tool-set full --mode careful
```

Useful for iterating on the prompt without launching the full eval. ~30
lines.

#### 5. Tests

**File**: `tests/test_tool_block.py` (new)

- `format_agent_tool_block(resolve_tool_set("full"), mode="careful")`
  contains expected substrings for each tool: "Inputs:", "Returns:",
  "When to use:", "Chains with:", "Example call:".
- `bbox_norm` is rendered as "array of 4 numbers" (or equivalent), NOT
  "?" or "tuple".
- `pixel` and `image_width` and `bbox_norm` all appear in the rendered
  text near `layout_detect` (proving the pixel-vs-norm chaining note
  surfaces).
- `crop_ref` and `image_refs` appear near `inspect_region` (proving
  the post-feed chaining note surfaces).
- Generic mode is shorter than careful mode by ≥ 30% (token-bound check).
- Worked example for each tool is a parseable JSON object whose `action`
  matches the tool name and whose `action_input` validates against the
  tool's `input_model`. (This is the strongest contract test — broken
  examples fail the build.)

**File**: `tests/test_react_agent.py` (extend)

- `_REACT_SYSTEM_PROMPT + tool block` includes "Chains with:" for every
  tool in `resolve_tool_set("full")`.
- AgentBaseline's prompt does NOT include "Chains with:" (generic mode).

### Success Criteria

#### Automated:

- [ ] `uv run pytest tests/test_tool_block.py tests/test_react_agent.py -q` passes.
- [ ] `uv run python scripts/dump_agent_prompt.py --tool-set full --mode careful` prints a non-empty block containing "Returns:" and "Chains with:".
- [ ] Each tool's worked example, when parsed as JSON and passed through `tool.input_model.model_validate(action_input)`, raises no `ValidationError`.
- [ ] `uv run ruff check src/focusparse/tools/ src/focusparse/pipeline/react_agent.py src/focusparse/pipeline/agent_baseline.py scripts/dump_agent_prompt.py` passes.

#### Manual:

- [ ] Diff the rendered prompt block before vs after at `--tool-set full`. Token count goes up (~3-5x) but examples and chaining notes are present.
- [ ] Spot-check on `gpt-5.4` with one example: ask the model to perform a `layout_detect → inspect_region → run_python` chain on a fixture PDF and confirm it produces correct calls without hand-holding.

**Phase 2 commits:** ~5 commits — `output_model` add to ToolSpec → renderer module → react/baseline switch → dump_agent_prompt CLI → tests.

---

## Phase 3: `run_python` ergonomic fixes — paths in, paths out

### Overview

Two changes:

1. `RunPythonOutput` gains `new_image_paths: list[str]` (absolute paths)
   alongside the existing `new_image_refs` (sha256 stems). The runner
   computes paths from the cache_dir at the parent boundary. The agent
   never has to think about cache-dir layout.
2. `_run_python_runner` (the agent-facing wrapper in `tools/__init__.py`)
   maps incoming crop-ref paths to ref-keyed `images` dict entries
   transparently. Currently the parent-side resolver in `run_python.py`
   already handles absolute paths, but the resulting `images` dict is
   keyed by the original input string. We add a contract: the input
   `image_refs` strings are exactly the keys in the sandbox's `images`
   dict.

Plus a documentation refresh: the `RUN_PYTHON_SPEC.description` is
extended with the worked example and the explicit allowlist.

### Changes Required

#### 1. `RunPythonOutput.new_image_paths`

**File**: `src/focusparse/tools/run_python.py`

```python
class RunPythonOutput(BaseModel):
    stdout: str
    stderr: str = ""
    new_image_refs: list[str] = Field(default_factory=list)
    new_image_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Absolute paths to PNGs written for each save_image() call. "
            "1:1 with new_image_refs. Pass either the ref or the path "
            "back into run_python.image_refs or inspect_region (via a "
            "subsequent call that takes a path)."
        ),
    )
    exit_code: int = 0
    timed_out: bool = False
```

Compute `new_image_paths` in `run_python` after writing each PNG to
disk:

```python
new_refs: list[str] = []
new_paths: list[str] = []
for png_bytes in payload.get("images", []):
    ref = hashlib.sha256(png_bytes).hexdigest()[:16]
    if new_image_cache_dir is not None:
        out_path = new_image_cache_dir / f"{ref}.png"
        out_path.write_bytes(png_bytes)
        new_paths.append(str(out_path))
    new_refs.append(ref)

return RunPythonOutput(
    stdout=...,
    new_image_refs=new_refs,
    new_image_paths=new_paths,
    ...
)
```

Note: when `new_image_cache_dir is None`, `new_image_paths` stays `[]`
(we can't fabricate a path without a cache root). `new_image_refs`
still gets populated (it's already memory-only). Tests cover this.

#### 2. Update `_summarize_run_python` to surface paths

**File**: `src/focusparse/tools/__init__.py:216-219`

```python
def _summarize_run_python(out: dict[str, Any]) -> str:
    stdout = (out.get("stdout") or "").strip().replace("\n", " ")[:300]
    n_new = len(out.get("new_image_paths") or out.get("new_image_refs") or [])
    paths = out.get("new_image_paths") or []
    paths_part = f", new_paths={paths[:2]}" if paths else ""
    return f"stdout={stdout!r}, n_new_images={n_new}{paths_part}, exit_code={out.get('exit_code')}"
```

#### 3. Update `RUN_PYTHON_SPEC.description`

**File**: `src/focusparse/tools/__init__.py:267-280`

Replace with (this is what the LLM sees in the careful prompt):

```python
RUN_PYTHON_SPEC = ToolSpec(
    name="run_python",
    description=(
        "Run sandboxed Python over previously-cropped images. "
        "Use for coding-driven zoom (LANCZOS upsample of tiny crops), "
        "peak detection on chart axes, or PIL-based annotation. "
        "Inside the sandbox: `images` is a dict keyed by the strings "
        "you passed as `image_refs`; values are PIL.Image objects. "
        "Call `save_image(img)` to return a new PNG (its absolute path "
        "comes back as one entry of `new_image_paths`). `print(...)` is "
        "captured into stdout. "
        "Allowlist: PIL, numpy, matplotlib, scipy, plus io/math/statistics/"
        "hashlib/json/base64/itertools/functools. Forbidden: os, subprocess, "
        "open(), exec(), eval(), socket. Wall-time cap is 15s by default."
    ),
    input_model=RunPythonInput,
    runner=_run_python_runner,
    summarize=_summarize_run_python,
    output_model=RunPythonOutput,
)
```

The Phase 1 `RunPythonInput.code.examples` already supplies the worked
template; this description ties it together.

#### 4. Tests

**File**: `tests/test_run_python.py` (extend)

- After `save_image(out)`, the returned `RunPythonOutput.new_image_paths`
  is non-empty, `Path(p).is_file()` is True for every entry, and
  `len(new_image_paths) == len(new_image_refs)`.
- When `new_image_cache_dir is None` (no cache supplied), the runner
  returns `new_image_paths == []` but `new_image_refs` still populated.
- An absolute crop_ref-style path passed in `image_refs` becomes an
  `images` dict key the sandbox can reference. The current test
  `test_image_round_trip_via_save_image` already covers the
  resolver-side; add a parallel test that asserts the round-trip key
  identity (input string == sandbox dict key).

**File**: `tests/test_tools.py` (extend)

- `_summarize_run_python({...})` includes `new_paths=...` when paths are
  present.

### Success Criteria

#### Automated:

- [ ] `uv run pytest tests/test_run_python.py tests/test_tools.py -q` passes.
- [ ] All existing `tests/test_run_python.py` tests still pass (back-compat: `new_image_refs` unchanged).
- [ ] `RunPythonOutput.model_json_schema()` contains `new_image_paths` with a non-empty `description`.
- [ ] `uv run ruff check src/focusparse/tools/run_python.py src/focusparse/tools/__init__.py` passes.

#### Manual:

- [ ] Run a one-liner: pass an `inspect_region.crop_ref` as `image_refs[0]`, do a 2× LANCZOS, observe `new_image_paths[0]` is a valid PNG path on disk.
- [ ] The path returned by `new_image_paths[0]` is itself usable as a subsequent `run_python.image_refs[0]` (re-feed loop works).

**Phase 3 commits:** ~3 commits — output schema add + tests, summarize + spec description refresh, integration test.

---

## Phase 4: Integration smoke — full chain on one fixture

### Overview

A single integration test that walks `layout_detect → inspect_region →
run_python` on a fixture PDF using a scripted-mock LLM (no API spend).
This is the canary that proves the documentation actually leads an LLM
to chain tools correctly. If we change a description in the future and
break the chaining contract, this test fails.

### Changes Required

#### 1. New test file `tests/test_tool_chain_integration.py`

```python
async def test_layout_detect_to_inspect_region_to_run_python_chain(
    parser_bench_submodule_present, tmp_path,
):
    """Walk a 3-tool chain end-to-end with a scripted LLM.

    The scripted client emits valid JSON tool calls in sequence:
      1. layout_detect on a fixture page → returns N regions
      2. inspect_region (mode=image) using regions[0].bbox normalized
         by image_width/image_height → returns a crop_ref
      3. run_python(code=lanczos_upsample, image_refs=[crop_ref]) →
         returns new_image_paths with a valid PNG on disk
      4. final_answer with a citation pointing at regions[0]

    Asserts: no tool_error steps; new_image_paths[0] exists on disk;
    scoring reward is non-zero.
    """
```

Uses `tests/fixtures/tiny_datasheet.pdf` + a small page PNG. Mocks the HF
layout endpoint via `httpx.MockTransport` to return a deterministic 2-box
response. Mocks the LLM via `_ScriptedClient` from
`tests/test_react_agent.py`.

#### 2. Tests for `scripts/dump_agent_prompt.py`

`tests/test_dump_agent_prompt.py` — runs the script in a subprocess and
asserts the output includes Phase 2's required substrings.

### Success Criteria

#### Automated:

- [ ] `uv run pytest tests/test_tool_chain_integration.py tests/test_dump_agent_prompt.py -q` passes.
- [ ] The scripted-mock chain produces zero `tool_error` steps in the recorded trace.

#### Manual:

- [ ] A real run on the trace viewer (`uv run python scripts/visualize_trace.py …`) for the integration test's prediction shows the chain visually: layout_detect output, inspect_region crop, run_python upsampled crop.

**Phase 4 commits:** 1-2 commits.

---

## Testing Strategy

### Unit Tests

- `tests/test_tools.py` — schema visibility, summarize content, registry shape.
- `tests/test_inspect_region.py` — field validation, bbox_norm shape.
- `tests/test_layout_detect.py` — `DetectedBox` fields surface, pixel-vs-norm clarity in description.
- `tests/test_run_python.py` — `new_image_paths` round-trip, both cache and no-cache modes.
- `tests/test_tool_block.py` (new) — renderer output for each tool: descriptions, examples, chaining, returns.
- `tests/test_react_agent.py` — the system prompt now includes "Chains with:" for every tool.
- `tests/test_dump_agent_prompt.py` (new) — CLI sanity.

### Integration Tests

- `tests/test_tool_chain_integration.py` (new) — full 3-tool chain with scripted-mock LLM and a fixture PDF.

### Manual Testing Steps

1. After Phase 1: `uv run python -c "from focusparse.tools.inspect_region import InspectRegionInput; import json; print(json.dumps(InspectRegionInput.model_json_schema(), indent=2))"` — eyeball that every field has a description and `bbox_norm` is rendered cleanly.
2. After Phase 2: `uv run python scripts/dump_agent_prompt.py --tool-set full` — read the rendered prompt block as if you were the agent. Can you build a `layout_detect → inspect_region → run_python` chain just from this text? If yes, the docs work.
3. After Phase 3: in a Python REPL, run `await run_python(...)` with a fixture crop and confirm `out.new_image_paths[0]` exists on disk and is a valid PNG.
4. After Phase 4: open the trace viewer for the integration test's example and visually confirm the chain executed.

## Performance Considerations

- **Prompt token growth.** The careful prompt block is ~3-5× larger than today's one-liner. With 4 tools + worked examples this is roughly 800-1200 additional tokens per system prompt. Acceptable for the `--tool-set full` rows; on a $0.005/1K-token tier this adds ~$0.005/example × 148 = ~$0.75 per full headline run. Within Phase-6 budget.
- **No runtime change.** Tool dispatch, sandbox, and cache hits are unchanged. The only added work is one-time JSON-Schema rendering at agent-construction time.
- **`new_image_paths` cost.** One additional `f"{ref}.png"` join per new image. Negligible.

## Migration Notes

- **`new_image_refs` stays.** The deterministic inspector's `_zoom_crop`
  in `pipeline/inspector.py:355-357` keeps using `new_image_refs` (it
  knows the cache dir already). We add `new_image_paths` alongside; we
  do not deprecate.
- **Trace schema unchanged.** No `SCHEMA_VERSION` bump needed — these
  changes are at the tool-spec layer, not the trajectory layer.
- **No cached predictions invalidated.** Existing `headline-v1`
  predictions stay readable. The new tool block only affects future
  agent runs.
- **`bbox_norm` model type changes from `tuple` to `list[float]`** for
  the cleaner JSON Schema. Pydantic still accepts tuple inputs and
  coerces; existing call sites (passing tuple literals) keep working.
  Verified by extending the existing schema test coverage.

## References

- **Active plan**: `plans/2026-04-29-research-driven-eval-framework.md` (Phase 6 candidate #1, "LLM-driven inspector dispatch", depends on this).
- **Prior sub-plan**: `plans/2026-05-04-react-fix-and-trace-viz.md` (Track C1 already shipped path-fairness; this plan extends the same "comparator hygiene" track at the schema level).
- **Standing context**: `.claude/memory/MEMORY.md` "Narrowed scope" section names `tools/*` as a primary optimization target.
- **Sandbox load-bearing contract**: `CLAUDE.md` — "Do not run `run_python`-authored code in-process." This plan documents but does not loosen the sandbox.
- **Files touched (read-only references for the implementer)**:
  - `src/focusparse/tools/inspect_region.py:44-62` — input/output models.
  - `src/focusparse/tools/layout_detect.py:39-50` — output models.
  - `src/focusparse/tools/get_text_layer.py:37-62` — input/output models.
  - `src/focusparse/tools/run_python.py:75-88` — input/output models.
  - `src/focusparse/tools/__init__.py:128-280` — registry, runners, specs.
  - `src/focusparse/pipeline/react_agent.py:269-283` — `_tool_block`, replaced.
  - `src/focusparse/pipeline/agent_baseline.py:74` — switches to generic mode.
  - `src/focusparse/pipeline/inspector.py:355-357` — keeps using `new_image_refs` (no change).
