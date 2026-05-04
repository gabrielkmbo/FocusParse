# Harness + tools iteration sprint (2-3 weeks)

## Overview

A focused 2-3 week sprint on the FocusParse harness — `inspect`, `expand_context`, and the
tool layer they call. Five Phase 6 candidates from the active research-driven-eval-framework
plan, each with a per-candidate A/B at n=148, capped by an end-of-sprint headline-v2 that
combines all default-on changes. The eval is the yardstick; the harness is the work.

**Priority order:** Phase 1 (#1 Inspector LLM-driven dispatch) → Phase 2 (#6 Multi-scale
packets) → Phase 3 (#7 chart_to_table) → Phase 4 (#2 Evidence-graph re-A/B) →
Phase 5 (#5 Auto-zoom re-A/B) → Phase 6 (headline-v2). If the priority trio (1, 6, 7) lands
cleanly, phases 4 + 5 are essentially free re-runs of already-wired flags.

**No spending constraint** per user 2026-05-04. Estimated total: ~$25-35 in API + ~3-5h
of wall time for evals across the sprint.

## Current State Analysis

### What this session has shipped (prerequisites for the sprint)

- **Trace v2 + viewer**: `RunTrace.evidence_snapshot` + `scripts/visualize_trace.py` +
  `scripts/visualize_examples.py`. Per-prediction HTML, openable from `file://`, base64
  crops + page overlays. Used as the visual A/B diff surface in this sprint.
- **Tool docs + sandbox ergonomics**: `format_agent_tool_block` renderer with worked
  examples + chaining notes (`careful` mode for ReAct + the future LLM-driven
  inspector); `run_python.new_image_paths`; field-level descriptions on every tool
  input/output model. The Phase 1 inspector LLM-dispatch consumes this directly.
- **Diagnostic mining**: `scripts/diagnose_predictions.py` confirms focus +4 has 15%
  lazy_answer_rate, 0% tool_error rate, 1.00 mean tool calls (the deterministic
  inspector counts as one tool_call). Tells us the inspector is the bottleneck for the
  remaining lazy answers.

### Headline-v1 baseline (the reference table for this sprint)

| Method             | Datasheets         | Finance            | Overall   | $/correct |
| ------------------ | ------------------ | ------------------ | --------- | --------- |
| Base VLM           | 42.6% [34.7, 52.5] | 31.9% [19.1, 46.8] | **39.2%** | $0.012    |
| ReAct +4           | 21.8 [13.9, 30.7]  | 14.9 [6.4, 25.5]   | 19.6      | $0.066    |
| Agent baseline +4  | 14.9 [7.9, 21.8]   | 6.4 [0.0, 14.9]    | 12.2      | $0.073    |
| **Our harness +4** | 45.5 [36.6, 54.5]  | 27.7 [14.9, 40.4]  | **39.9%** | $0.017    |

Datasheets nominally ahead (+2.9pp); Finance behind (-4.2pp); Overall within sample variance
(+0.7pp). Phase 6 work targets non-overlapping CI on Overall, especially via the Finance cell.

### Key Discoveries (informing this sprint)

- **Inspector ranks text > picture by RT-DETRv2 detector score** (`pipeline/inspector.py:166-169`).
  Figure-heavy questions miss because text regions outrank chart regions. This is the
  Phase 1 lever.
- **EvidencePacket has only `local_crop_ref` + `linked_crop_refs`** (`evidence/packet.py:39-41`).
  No multi-scale support; the reasoner sees one tight crop without context. Phase 2 lever.
- **`chart_to_table.py` is a stub** (`tools/chart_to_table.py:31`) raising
  `NotImplementedError`. Phase 3 implements the gridline + axis OCR fusion that the
  comment block describes.
- **`--use-evidence-graph` and `--auto-zoom` flags exist** (`pipeline/workflow.py:91-94`)
  but default off due to broken-scorer A/Bs in 2026-04-27. Need re-A/B under current
  scoring + post-rerank conditions. Phases 4-5 levers.
- **Focus +4 inspector calls deterministic_inspector exactly once per example**
  (mean_tool_calls = 1.00). The inspector is the _one_ deterministic decision point;
  changing it to LLM-dispatch fans this out into N targeted tool calls.

## Desired End State

After this sprint:

1. **Headline-v2 table** at n=148, agentic_multi_page protocol, gpt-5.4 reasoner — all
   default-on phase-1/2/3/4/5 changes layered. Renders to
   `results/hf/headline-v2/headline_table.{json,md,html}`.
2. **Our harness +4 dominates** Base VLM by ≥3pp on Overall at non-overlapping CIs, OR
   we have a clear failure-mode autopsy in MEMORY.md explaining why each phase didn't
   move the cell.
3. **Per-phase trace HTMLs** at `results/trace_viewer/sprint-2026-05-04/<phase>/` for 4
   representative examples (correct/wrong/lazy/recovered) so the visual diff is
   inspectable end-to-end.
4. **HF dataset pinned** in `configs/default.yaml` so all sprint A/Bs run on the same
   n=148, even if the dataset advances mid-sprint.
5. **MEMORY.md changelog entries** per phase with the 4-question rubric (cell, lift,
   mechanism, A/B with CIs).

### Success criteria for v1 of this sprint

- All 5 phases run their A/B; each ends with a memory entry.
- At least one phase shows ≥3pp non-overlapping CI on at least one cell of Our harness +4.
- Headline-v2 reproducibility gate: `simple/full_doc` matches parser-bench published 48.6%
  within ±2pp.

## What We're NOT Doing

- **No cross-model appendix.** Re-running the harness on Gemini / Claude is Phase 7 of
  the active plan; it doesn't address the user's "harness + tools" priority. Defer.
- **No comparator polish.** ReAct / AgentBaseline stay frozen per the active plan's
  development priority rule. The C3 ReAct re-run from the prior sub-plan stays held.
- **No new tools beyond chart_to_table.** `inspect_region`, `get_text_layer`,
  `layout_detect`, `run_python` keep their current API. chart_to_table moves from
  stub to implemented.
- **No trace schema bumps beyond v2.** This session shipped v2; schema work is done.
- **No oracle ceilings.** Phase 7 appendix work; defer.
- **No Phase 8 (router visual recall, learned policy, hard-negative mining).** All
  beyond this sprint's scope.

## Implementation Approach

Six phases. Each lands as multiple small commits per `feedback_commit_granularity`. Each
ends with: tests green; a per-candidate A/B at n=148; a memory entry; auto-emitted trace
HTMLs. Phases 1-5 are independent (any can ship-or-revert without blocking the others).
Phase 6 is the rollup.

---

## Phase 0: HF dataset pin + reproducibility gate

### Overview

Pin the new HF dataset revision (the user updated `gabrielbo/parser-bench` on 2026-05-04)
so every sprint A/B compares against the same n=148. Then run the reproducibility gate
(simple/full_doc on default tier) to confirm scoring + tier router still match
parser-bench's published GPT-5.4 baseline within ±2pp.

### Changes Required

#### 1. Dataset revision pin

**File**: `configs/default.yaml`
**Changes**: Update `dataset.revision` from `null` to the latest HF Hub commit SHA on
`gabrielbo/parser-bench`. Also bump `traces.schema_version: "1"` → `"2"` (this session's
schema bump landed but the YAML still reads "1").

```yaml
dataset:
  source: hf
  hf_repo: gabrielbo/parser-bench
  revision: <new-sha> # was null pre-2026-05-04
  local_root: null

traces:
  schema_version: "2" # bumped 2026-05-04 with evidence_snapshot
```

Resolution: `git ls-remote https://huggingface.co/datasets/gabrielbo/parser-bench refs/heads/main` (or use
`huggingface_hub.HfApi().list_repo_refs()`) to get the SHA. Document the SHA in the
memory entry alongside what changed (counts/schema if any).

#### 2. Reproducibility gate

```bash
uv run python scripts/run_hf_eval.py \
  --agent simple --protocol full_doc \
  --output-dir results/hf/sprint-repro/repro-arm \
  --staging-dir ~/.cache/focusparse/hf_staging \
  --pdfs-root ~/.cache/focusparse/pdfs
```

Assert: `simple/full_doc` accuracy ∈ [46.6, 50.6] (parser-bench 48.6% ±2pp). If outside
that band, halt the sprint and audit scoring before proceeding.

#### 3. Memory entry

Append a dated entry to `.claude/memory/project_changelog.md`:

- HF revision pinned: `<sha>`.
- Schema version YAML bump (cosmetic — runtime constant already at "2").
- Reproducibility gate result.
- 4Q rubric for the rest of the sprint: cell = `Our harness +4 / Overall / accuracy`,
  baseline 39.9% [31.8, 47.3], target ≥ Base VLM + 3pp at non-overlapping CIs.

### Success Criteria

#### Automated:

- [ ] `uv run pytest` full suite stays green (~564 + future additions).
- [ ] `simple/full_doc` n=148 manifest shows accuracy ∈ [46.6, 50.6].
- [ ] `configs/default.yaml::dataset.revision` is a non-null commit SHA.

#### Manual:

- [ ] Spot-check that the new dataset's example count is still 148 (101 datasheet + 47
      finance) before any A/B fires.

**Cells affected:** none. Sets the baseline.

---

## Phase 1: Inspector LLM-driven dispatch (Phase 6 #1)

### Overview

Replace the deterministic top-N + region-routed inspector
(`pipeline/inspector.py:125-183`) with a ReAct-style sub-loop where an LLM decides
_which_ regions to inspect with _which_ `inspect_region` mode. Consumes the tool docs
shipped this session (`format_agent_tool_block(careful)`); the LLM gets the worked
examples + chaining contract for free.

This is the #1 Phase 6 candidate per the active plan and the #1 lever per the
diagnostic mining: focus +4's deterministic inspector is the one decision point we can
change for biggest predicted lift.

### Changes Required

#### 1. New module `src/focusparse/pipeline/inspector_react.py`

```python
class ReActInspector:
    """LLM-driven inspector — decides which regions × which mode to inspect.

    Drop-in replacement for `inspect_regions(...)` when
    `FocusWorkflow(use_react_inspector=True)`. The deterministic inspector
    stays as the floor we A/B against.
    """

    def __init__(
        self,
        *,
        backend_client: ModelClient,
        max_iterations: int = 4,
    ) -> None: ...

    async def inspect(
        self,
        question: QuestionEvent,
        plan: PlanEvent,
        regions: RegionsEvent,
        *,
        images_by_page: dict[int, Path],
        pdf_path: Path | None,
        crop_cache_dir: Path | None,
        text_layer_cache_dir: Path | None,
    ) -> EvidenceEvent: ...
```

Loop body:

1. LLM sees question + region candidates (page + bbox + region_type + score).
2. Each turn emits `{"region_idx": int, "tool": "inspect_region|get_text_layer|run_python",
"args": {...}}` OR `{"done": true}`.
3. Harness dispatches via `tools.resolve_tool_set("full")` — same registry the
   ReActAgent uses.
4. Up to `max_iterations` (default 4) tool calls per example.
5. Resulting `EvidencePacket`s assembled from successful tool outputs.

System prompt uses `format_agent_tool_block(resolve_tool_set("full"), mode="careful")`
so the LLM sees the chaining contract (pixel→norm conversion, crop_ref→image_refs)
documented this session. Prompt names each region candidate with index + page +
region_type + bbox_norm + score.

#### 2. FocusWorkflow flag

**File**: `src/focusparse/pipeline/workflow.py`

Add `use_react_inspector: bool = False` to `FocusWorkflow.__init__`. When True,
`_run_inspect` routes through `ReActInspector` instead of `inspect_regions`.

```python
if self.use_react_inspector:
    inspector = ReActInspector(backend_client=self._client_for("inspector_dispatch"))
    evidence = await inspector.inspect(question_event, plan, regions, ...)
else:
    evidence = await inspect_regions(...)  # existing deterministic path
```

#### 3. Tier-router slot for the inspector LLM

**File**: `configs/default.yaml`

```yaml
roles:
  planner: cheap
  router: cheap
  localizer_rerank: mid
  inspector_dispatch: mid # NEW — LLM-driven inspector tier
  reasoner: frontier
  verifier: mid
```

`mid` (claude-haiku-4-5) is the right tier: the inspector loop is short (≤4 turns),
needs structured JSON, and shouldn't blow the budget on frontier tokens.

#### 4. CLI flag on `scripts/run_hf_eval.py`

```python
parser.add_argument("--react-inspector", action="store_true",
                    help="Use the LLM-driven inspector dispatch (Phase 6 #1).")
```

Threaded into the `FocusWorkflow` ctor.

#### 5. Tests

**File**: `tests/test_inspector_react.py` (new)

- Mock backend that emits a 2-step dispatch: (1) inspect_region(image), (2) done.
- Assert: 2 packets produced; both have `local_crop_ref` populated.
- Tool error handling: dispatch emits an unknown tool → loop continues, no crash.
- max_iterations cap: scripted 6-turn loop with max=3 → exactly 3 dispatches.

**File**: `tests/test_workflow.py` (extend)

- `FocusWorkflow(use_react_inspector=True)` end-to-end with mock backend; trace shows
  inspector_dispatch tier and ≥1 LLM call inside the inspector stage.

#### 6. A/B at n=148

```bash
uv run python scripts/run_hf_eval.py --agent focus --tool-set full \
  --protocol agentic_multi_page --react-inspector \
  --output-dir results/hf/sprint-2026-05-04/phase1-react-inspector \
  --staging-dir ~/.cache/focusparse/hf_staging \
  --pdfs-root ~/.cache/focusparse/pdfs

uv run python scripts/diff_runs.py \
  results/hf/headline-v1/focusparse_focus_agentic_multi_page_*/run.json \
  results/hf/sprint-2026-05-04/phase1-react-inspector/run.json
```

Auto-emit 4 trace HTMLs (correct-by-Phase1-only, correct-by-baseline-only,
wrong-by-both, lazy-recovered) into `results/trace_viewer/sprint-2026-05-04/phase1/`.

**Decision rule:**

- ≥+3pp non-overlapping CI on Overall accuracy: flip default to `use_react_inspector=True`.
  Update `_DEFAULT_USE_REACT_INSPECTOR = True` in workflow.py.
- ≥+1pp on Datasheets only: ship as opt-in flag, leave default off, update memory entry
  with the partial result.
- ≤baseline or regressed: ship as opt-in flag, write the autopsy in MEMORY.md, move on.

#### 7. Memory entry

4Q rubric:

1. Cell: `Our harness +4 / both domains / accuracy`.
2. Predicted: +3-7pp on Datasheets; ±2pp on Finance.
3. Mechanism: LLM picks figure-heavy regions over text regions for chart questions
   (RT-DETRv2 score-ordering footgun); ReAct prompt requires bbox-grounded
   citations (carryover from this session's prompt fix).
4. A/B result: actual deltas + CIs.

### Success Criteria

#### Automated:

- [ ] `uv run pytest tests/test_inspector_react.py tests/test_workflow.py -v` passes.
- [ ] `uv run ruff check src/focusparse/pipeline/inspector_react.py` passes.
- [ ] Phase 1 spec produces 148 predictions; tool_error_rate < 5% in the diagnostic
      report (re-run `scripts/diagnose_predictions.py --spec-dir
results/hf/sprint-2026-05-04/phase1-react-inspector`).

#### Manual:

- [ ] Open 4 trace viewers; spot-check that the LLM picked picture/chart regions on at
      least 2 finance examples where the deterministic inspector picked text.
- [ ] Memory entry honestly states the three-way decision outcome.

**Cells affected:** Our harness +4 (4 cells: Datasheets/Finance × accuracy/$/correct).
**Estimated cost:** ~$3-5 ($0.02/example × 148 = $3 for the focus run; +$0.005 inspector
LLM × 4 turns × 148 = $3 — total ~$5-6).

---

## Phase 2: Multi-scale evidence packets (Phase 6 #6)

### Overview

Extend `EvidencePacket` with `multi_scale_crops: list[CropRef]` so the reasoner sees both
a tight crop AND a wider context view of the same region. Today's packet has just one
`local_crop_ref`; charts often need axis labels / legends in the context, footnotes
need a wider rect, and tables need their headers. Reasoner can then reason over both
scales without re-calling `inspect_region`.

### Changes Required

#### 1. Extend `EvidencePacket`

**File**: `src/focusparse/evidence/packet.py`

```python
class CropRef(BaseModel):
    """A single crop with its scale and bbox."""
    ref: str                                    # absolute path
    bbox_norm: tuple[float, float, float, float]
    scale: Literal["tight", "context"] = "tight"

class EvidencePacket(BaseModel):
    ...existing fields...
    multi_scale_crops: list[CropRef] = Field(
        default_factory=list,
        description=(
            "All crop scales for this region. Element 0 is the tight crop "
            "(== local_crop_ref); subsequent elements are wider context "
            "(typically ~30% pad) for the same bbox."
        ),
    )
```

`local_crop_ref` stays as the canonical primary crop for back-compat; the reasoner
prompt iterates `multi_scale_crops` if non-empty.

#### 2. Inspector builds context crop alongside tight crop

**File**: `src/focusparse/pipeline/inspector.py:_inspect_one_region`

After the existing `inspect_region(mode="image", expansion="default")` call, run a
second `inspect_region(mode="image", expansion="aggressive")` on a 30%-padded bbox.
Both crop refs go into `multi_scale_crops`.

```python
context_bbox = _expand_bbox(region.bbox_norm, pad=0.30)
ctx_out = await inspect_region(
    InspectRegionInput(
        doc_path=str(pdf_path),
        page=region.page,
        bbox_norm=context_bbox,
        mode="image",
        expansion="none",  # already padded; don't double-expand
    ),
    cache_dir=crop_cache_dir,
)
multi_scale_crops = [
    CropRef(ref=tight_crop_ref, bbox_norm=region.bbox_norm, scale="tight"),
    CropRef(ref=ctx_out.crop_ref, bbox_norm=context_bbox, scale="context"),
]
```

Helper: `_expand_bbox(bbox, pad)` adds `pad` to each side, clamped to [0,1].

#### 3. Reasoner prompt threads both scales

**File**: `src/focusparse/pipeline/reasoner.py`

Existing prompt builds one image per packet from `local_crop_ref`. Extend to enumerate
`packet.multi_scale_crops` (when non-empty) so the reasoner sees both:

```
Evidence packet 1 (page 3):
  - tight crop: <image_1a>
  - context crop: <image_1b>
  - text layer: ...
```

Two images per packet doubles the visual token count but stays within the budget for
agentic_multi_page (mean ≈ 4 packets → 8 images at most).

#### 4. Trace recorder serializes both refs

**File**: `src/focusparse/pipeline/workflow.py:_packet_to_summary`

Update the `EvidencePacketSummary` builder (this session's helper) to include
`multi_scale_crops`. Schema-additive, no v2 → v3 bump needed; the new field is optional
and absent from older traces.

Or: add `multi_scale_crops: list[dict] | None = None` to `EvidencePacketSummary` directly.

#### 5. CLI flag

```python
parser.add_argument("--multi-scale-packets", action="store_true",
                    help="Build tight + context crops per packet (Phase 6 #6).")
```

`FocusWorkflow.__init__` gains `multi_scale_packets: bool = False`. Inspector + reasoner
respect it.

#### 6. Tests

**File**: `tests/test_inspector.py` (extend)

- With `multi_scale_packets=True`, each packet has `len(multi_scale_crops) == 2`.
- Both crop_refs point at existing PNGs on disk after the inspect run.
- Disabled by default: existing tests stay green without modification.

**File**: `tests/test_reasoner.py` (extend if exists, else new)

- Reasoner prompt with multi-scale packets has 2× the image inputs of single-scale.

#### 7. A/B at n=148

```bash
uv run python scripts/run_hf_eval.py --agent focus --tool-set full \
  --protocol agentic_multi_page --multi-scale-packets \
  --output-dir results/hf/sprint-2026-05-04/phase2-multi-scale \
  ...
uv run python scripts/diff_runs.py \
  results/hf/headline-v1/.../run.json \
  results/hf/sprint-2026-05-04/phase2-multi-scale/run.json
```

Decision rule + memory entry: same shape as Phase 1.

### Success Criteria

#### Automated:

- [ ] `uv run pytest tests/test_inspector.py tests/test_packet.py tests/test_reasoner.py -v` passes.
- [ ] Phase 2 spec produces 148 predictions; per-packet `multi_scale_crops` length = 2.

#### Manual:

- [ ] Open 4 trace viewers; spot-check that both crop scales render inline.
- [ ] Memory entry honestly states the outcome.

**Cells affected:** Our harness +4 (4 cells).
**Estimated cost:** ~$3-5 (inspector latency doubles per region; reasoner sees more
input tokens).

---

## Phase 3: chart_to_table specialist tool (Phase 6 #7)

### Overview

Implement the `chart_to_table` tool that's currently a stub. Targets Finance accuracy
specifically — chart-reading is where Our harness +4 trails Base VLM (-4.2pp). Router
uses it only for `question_family ∈ {axis_value_interpolation,
candlestick_ohlc_extraction}` so most examples stay on the existing path.

### Changes Required

#### 1. Implement `src/focusparse/tools/chart_to_table.py`

Replace `raise NotImplementedError` with:

```python
async def chart_to_table(
    inp: ChartToTableInput,
    *,
    crop_cache_dir: Path | None = None,
) -> ChartToTableOutput:
    """Extract tabular data from a chart crop.

    Pipeline:
      1. Load the crop PNG.
      2. Detect the plot area via gridline peak detection (scipy.signal.find_peaks
         on row/col sums of the binary edge map).
      3. OCR the axis tick labels via pytesseract (reuse `_ocr_crop` from
         inspect_region.py — refactor into a shared helper if needed).
      4. Interpolate data points: for each pixel column, find the y-coord of the
         darkest pixel in the plot area; convert to data coords via the OCR'd
         axis ticks.
      5. Emit CSV: `x_value,y_value,series_name`.
    """
```

Implementation lives in `src/focusparse/tools/_chart_extraction.py` (new helper module)
to keep the tool spec thin. Uses scipy + numpy + PIL — all in the run_python sandbox
allowlist, so the same code can be invoked from `run_python` for ad-hoc calls.

#### 2. Tool registry entry

**File**: `src/focusparse/tools/__init__.py`

```python
from focusparse.tools.chart_to_table import (
    ChartToTableInput,
    ChartToTableOutput,
    chart_to_table as _chart_to_table,
)

async def _chart_to_table_runner(...) -> dict[str, Any]:
    out = await _chart_to_table(inp, crop_cache_dir=crop_cache_dir)
    return out.model_dump()

CHART_TO_TABLE_SPEC = ToolSpec(
    name="chart_to_table",
    description=(
        "Extract tabular data from a chart crop via gridline peak detection "
        "and axis OCR. Use ONLY for chart-reading questions where exact "
        "axis-value interpolation matters. Otherwise inspect_region is "
        "sufficient. confidence=0.5 by default; verifier should double-check."
    ),
    input_model=ChartToTableInput,
    runner=_chart_to_table_runner,
    summarize=_summarize_chart_to_table,
    output_model=ChartToTableOutput,
)
```

`CHART_TO_TABLE_SPEC` is gated behind a NEW tool set: `_FULL_PLUS_CHART = _FULL_TOOLS +
(CHART_TO_TABLE_SPEC,)`. Add `--tool-set full+chart` CLI option. Comparator agents
(ReAct, AgentBaseline) get this set when run with the new flag; FocusWorkflow's
inspector router uses it only via the question-family conditional below.

#### 3. Inspector / reasoner conditional

**File**: `src/focusparse/pipeline/inspector.py`

```python
_CHART_QUESTION_FAMILIES = frozenset({
    "axis_value_interpolation",
    "candlestick_ohlc_extraction",
})

async def _inspect_one_region(...):
    ...existing logic...
    is_chart_question = (plan.question_family in _CHART_QUESTION_FAMILIES)
    is_chart_region = region_type in _VISUAL_REGION_TYPES and figure_class in {
        "bar_chart", "line_chart", "candlestick"
    }
    if is_chart_question and is_chart_region:
        chart_table = await chart_to_table(
            ChartToTableInput(crop_ref=crop_ref),
            crop_cache_dir=crop_cache_dir,
        )
        # Stamp the table into the packet for the reasoner.
        packet.chart_csv = chart_table.table_csv
```

Add `chart_csv: str | None = None` to `EvidencePacket`.

#### 4. Reasoner prompt mentions the table

When `packet.chart_csv` is non-null, the reasoner prompt includes it as a code-fenced
block before the crop:

````
Evidence packet 3 (page 7, chart):
  Tabular extraction (confidence=0.5):
  ```csv
  x,y,series
  1.0,2.3,sales
  ...
````

Crop: <image_3>

````

#### 5. Tests

**File**: `tests/test_chart_to_table.py` (new)
- Synthetic bar chart PNG (numpy + PIL): 3 bars at known heights.
- `chart_to_table` returns CSV with 3 rows; y-values within ±10% of ground truth.
- Confidence reflects OCR quality.

**File**: `tests/test_inspector.py` (extend)
- When `plan.question_family == "axis_value_interpolation"` and a chart region is
  inspected, the resulting packet's `chart_csv` is non-None.

#### 6. A/B at n=148 (finance subset only)

```bash
uv run python scripts/run_hf_eval.py --agent focus --tool-set full+chart \
  --protocol agentic_multi_page \
  --output-dir results/hf/sprint-2026-05-04/phase3-chart-table \
  ...
````

Diff focuses on the Finance domain (chart-heavy). Datasheets cell shouldn't move much
(no chart questions); if it does, debug.

Decision rule: ≥+3pp on Finance / non-overlapping CI → ship default-on for chart
question families. Datasheet regression > 1pp → revert.

### Success Criteria

#### Automated:

- [ ] `uv run pytest tests/test_chart_to_table.py tests/test_inspector.py -v` passes.
- [ ] Synthetic chart test extracts 3 bars within ±10% of ground truth.
- [ ] Phase 3 spec produces 148 predictions; chart_to_table fired on >0 finance examples.

#### Manual:

- [ ] Open 4 trace viewers (3 finance + 1 datasheet); the CSV block renders alongside
      the crop on chart questions.

**Cells affected:** Our harness +4 / Finance / accuracy + $/correct primarily.
**Estimated cost:** ~$3-5 + ~half-day of implementation. Scipy peak-detection runs in
the inspector path, no extra LLM cost for the extraction itself.

---

## Phase 4: Evidence-graph re-A/B (Phase 6 #2)

### Overview

`--use-evidence-graph` is wired but defaults off after a 2026-04-27 broken-scorer A/B
showed regressions. Re-run at n=148 under the current scorer and post-rerank conditions
to see whether the typed-graph expansion helps.

### Changes Required

No code changes (the flag exists). Just the A/B run + decision.

#### 1. A/B at n=148

```bash
uv run python scripts/run_hf_eval.py --agent focus --tool-set full \
  --protocol agentic_multi_page --use-evidence-graph \
  --output-dir results/hf/sprint-2026-05-04/phase4-graph-on \
  ...
uv run python scripts/diff_runs.py \
  results/hf/headline-v1/.../run.json \
  results/hf/sprint-2026-05-04/phase4-graph-on/run.json
```

#### 2. Decision rule

- ≥+3pp non-overlapping on Datasheets bbox_iou OR accuracy → flip default to
  `use_evidence_graph=True` in `workflow.py:_DEFAULT_USE_EVIDENCE_GRAPH`.
- Within ±2pp → keep opt-in.
- Regression → keep opt-in, document why in MEMORY.md.

#### 3. Memory entry

Same 4Q rubric structure as Phases 1-3.

### Success Criteria

#### Automated:

- [ ] Phase 4 spec produces 148 predictions; trace shows `use_evidence_graph=True` in
      the workflow plan block.
- [ ] `uv run python scripts/diff_runs.py ...` exits 0 with a deltas table.

#### Manual:

- [ ] Memory entry states the decision honestly.

**Cells affected:** Our harness +4 / Datasheets / bbox_iou + accuracy.
**Estimated cost:** ~$2.

---

## Phase 5: Auto-zoom re-A/B (Phase 6 #5)

### Overview

`--auto-zoom` is wired but defaults off. Targets visual-reading questions (axis_value
interpolation, confusable_label) where tiny crops (< 0.5% area) need 2× LANCZOS
upsample via `run_python`.

### Changes Required

No code changes. Just the A/B + decision.

```bash
uv run python scripts/run_hf_eval.py --agent focus --tool-set full \
  --protocol agentic_multi_page --auto-zoom \
  --output-dir results/hf/sprint-2026-05-04/phase5-auto-zoom \
  ...
```

Decision rule: ≥+2pp non-overlapping on the visual-reading question subset → flip
default. Otherwise opt-in.

### Success Criteria

#### Automated:

- [ ] Trace shows `run_python:zoom2x` provenance on at least one packet for examples
      with bbox area < 0.005.

#### Manual:

- [ ] One trace viewer for an axis_value_interpolation example shows the zoomed crop
      inline.

**Cells affected:** Our harness +4 / Datasheets / accuracy on visual-reading subset.
**Estimated cost:** ~$2.

---

## Phase 6: End-of-sprint headline-v2

### Overview

Re-run all 7 specs at n=148 with all default-on phase-1/2/3/4/5 changes layered.
Compare cell-by-cell vs headline-v1. Auto-emit trace viewers for the 4-bucket sample.

### Changes Required

#### 1. Headline orchestrator pickup

`scripts/run_headline_eval.py` should pick up the new defaults automatically (it shells
out to `run_hf_eval.py` which reads the workflow defaults). No code change needed
unless any phase ships an opt-in-only flag we want included in the headline; in that
case, add it to `run_headline_eval.py::HEADLINE_SPECS` for the focus rows.

#### 2. Run

```bash
uv run python scripts/run_headline_eval.py \
  --output-dir results/hf/headline-v2 \
  --max-parallel 4 \
  --pdfs-root ~/.cache/focusparse/pdfs \
  --staging-dir ~/.cache/focusparse/hf_staging
```

#### 3. Render + auto-emit viewers

```bash
uv run python scripts/render_headline_table.py results/hf/headline-v2/

uv run python scripts/visualize_examples.py \
  --headline-dir results/hf/headline-v2 \
  --output-dir results/trace_viewer/headline-v2/
```

#### 4. Diff vs headline-v1

```bash
# Per-spec diffs.
for spec in headline-v1/focusparse_*; do
  matched=$(basename $spec | sed 's|^headline-v1/|headline-v2/|')
  uv run python scripts/diff_runs.py \
    "results/hf/headline-v1/$spec/run.json" \
    "results/hf/headline-v2/$matched/run.json"
done
```

#### 5. Memory entry — the rollup

Append the v2 table to `.claude/memory/MEMORY.md` and write the sprint summary:

- v1 vs v2 cell deltas.
- Which phases moved which cells (attribution table).
- Decision: does Our harness +4 dominate Base VLM by ≥3pp on Overall at non-overlapping
  CIs? If yes, the paper claim sharpens. If no, what's the next sub-plan candidate?

### Success Criteria

#### Automated:

- [ ] `headline_table.json` has all 28 cells populated with bootstrap CIs.
- [ ] Reproducibility appendix: `simple/full_doc` v2 within ±2pp of parser-bench 48.6%.
- [ ] `results/trace_viewer/headline-v2/index.html` opens with all 28 spec viewers
      reachable.

#### Manual:

- [ ] Sprint summary memory entry written.
- [ ] Visual diff: open 1 v1 vs v2 trace viewer for the same example_id; confirm the
      v2 changes are visible (more tool calls, multi-scale crops, etc.).

**Cells affected:** all 28 (re-baselined).
**Estimated cost:** ~$10-15 (1036 calls × $0.005-0.025 = $5-25; mid-range estimate).

---

## Testing Strategy

### Unit Tests (new or extended per phase)

- `tests/test_inspector_react.py` (new) — Phase 1.
- `tests/test_workflow.py` (extend) — Phase 1 + Phase 2 flags.
- `tests/test_inspector.py` (extend) — Phase 2 + Phase 3.
- `tests/test_packet.py` (extend) — Phase 2 multi_scale_crops.
- `tests/test_reasoner.py` (extend or new) — Phase 2 multi-scale prompt.
- `tests/test_chart_to_table.py` (new) — Phase 3.

### Integration Tests

- `tests/test_focus_harness.py` (extend) — end-to-end run with each phase's flag.
- The existing `tests/test_tool_chain_integration.py` already covers
  layout_detect → inspect_region; a future variant may cover the Phase 1 ReAct
  inspector.

### Manual Testing

1. After each phase: open 4 trace HTMLs side-by-side with their headline-v1
   counterparts; visually confirm the change.
2. After Phase 6: skim `results/trace_viewer/headline-v2/index.html`; confirm the
   ✓/✗ grid moves in the expected direction.

## Performance Considerations

- **Phase 1 inspector LLM tier**: claude-haiku-4-5 (mid). 4 turns × 148 examples ≈ 600
  LLM calls. ~$3 at ~$0.005/call.
- **Phase 2 multi-scale**: doubles inspect_region calls per packet → ~2× crop-render
  cost (still cheap; PyMuPDF + PIL). Cache hits dominate after the first run.
- **Phase 3 chart_to_table**: scipy peak-detection is ~10ms per crop. Negligible.
- **Phase 6 headline-v2**: ~$10-15. Acceptable per user.
- **Total sprint cost**: ~$25-35.
- **API rate limits**: All phases run at `--max-parallel 4` (OpenAI-rate-limit-safe at
  gpt-5.4 per the prior full-eval).

## Migration Notes

- **Trace schema stays at v2.** No bump needed for any phase. `multi_scale_crops` and
  `chart_csv` are additive-optional fields; older traces parse cleanly with them
  defaulted to None / [].
- **Cached predictions in headline-v1/ stay readable.** A/B diffs read both v1 and v2
  per-example records. The diff harness handles missing fields.
- **`new_image_refs` (this session) stays for back-compat** even though `new_image_paths`
  is the agent-friendly path. No deprecation in this sprint.
- **HF dataset revision pin** is the only config change; rolling back is one YAML edit.

## References

- **Active plan**: `plans/2026-04-29-research-driven-eval-framework.md` — Phase 6
  candidate list.
- **Prior session sub-plans (prerequisites)**:
  - `plans/2026-05-04-react-fix-and-trace-viz.md` — trace v2 + viewer.
  - `plans/2026-05-04-tool-docs-and-sandbox-ergonomics.md` — tool docs + run_python
    ergonomics that Phase 1 consumes.
- **Standing context**: `.claude/memory/MEMORY.md` "Research framework" + "Narrowed
  scope" sections.
- **Headline-v1 results**: `results/hf/headline-v1/headline_table.{json,md,html}`.
- **Diagnostic baseline**: `results/diagnostics/headline-v1/report.md` (this session).
