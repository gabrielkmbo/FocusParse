# Phase 6 sub-plan — Diagnose, visualize, repair ReAct

## Overview

A focused three-track Phase 6 sub-plan that (A) instruments and verifies the
real failure modes behind the headline-v1 numbers, (B) ships a single-file
HTML trace viewer so we can inspect any one prediction end-to-end, and (C)
fixes ReAct's actual bottleneck (lazy answers + missing citations, not
path hallucination as previously assumed) so the comparator-gap claim
in the headline table is defensible.

This is a sub-plan of `plans/2026-04-29-research-driven-eval-framework.md`
Phase 6. Standing rules from the active plan apply: every change must move a
specific cell in the headline table or be classed as fairness/diagnostics work
(comparator hygiene).

## Current State Analysis

### What the n=148 headline run (2026-04-29) actually says

| Method                  | Datasheets         | Finance            | Overall     | $/correct |
| ----------------------- | ------------------ | ------------------ | ----------- | --------- |
| Base VLM                | 42.6% [34.7, 52.5] | 31.9% [19.1, 46.8] | 39.2%       | $0.012    |
| ReAct +2 / +4           | 18.8 / 21.8        | 10.6 / 14.9        | 16.2 / 19.6 | $0.07     |
| Agent baseline +2 / +4  | 14.9 / 14.9        | 6.4 / 6.4          | 12.2 / 12.2 | $0.07     |
| **Our harness +2 / +4** | **46.5 / 45.5**    | 23.4 / 27.7        | 39.2 / 39.9 | $0.017    |

ReAct lags Base VLM by ~20pp. The handoff
(`thoughts/shared/handoffs/general/2026-05-04_11-35-53_focusparse-headline-table-next-steps.md`)
attributes this to path hallucination in
`src/focusparse/pipeline/react_agent.py:227-244`. **A direct mining of the
148 ReAct +4 predictions falsifies that hypothesis.**

### Key Discoveries

- **Tool-error rate on ReAct is 3.5%** (8/226 steps across n=148). Half are
  `validation_error` (bbox out of range), half `tool_runtime_error` (malformed
  inputs). Hallucinated paths (`<uploaded_doc>`, `document.pdf`) appear in ~4
  steps total — not the dominant failure mode.
- **The dominant failure is lazy `final_answer`**: ReAct emits `final_answer`
  with empty `citations` on the bulk of examples even after at least one tool
  call succeeded. With no bbox commitment, `score_evidence_reward` (`src/focusparse/eval/scoring.py`) collapses to ~0, and answer correctness alone has to carry the score.
- **Per-example traces are already on disk in full.** `_score_and_record`
  (`src/focusparse/eval/harness.py:843-882`) embeds `result.trace.steps` into
  every `predictions/<id>.json`. No separate `traces.jsonl` exists. **But
  `obs_summary` and `confidence` are dropped during serialization** —
  see `_score_and_record` — so the LLM's actual turn text and the
  inspector's per-step confidence are lost on disk.
- **EvidencePacket crop refs (`local_crop_ref`, `linked_crop_refs`) are not
  on disk.** `EvidencePacket` lives in-memory inside the workflow. To
  visualize what the reasoner saw, we need to snapshot final packets into the
  `RunTrace` at finalize time. This is a load-bearing schema change
  (`SCHEMA_VERSION` bump).
- **`scripts/smoke_visualize.py`** exists as console-only prior art (PNG
  bbox overlays + printed trajectory). Not HTML, not interactive, not the
  right surface for cross-spec comparison.
- **ReAct's `_initial_user_turn`** does say "PDF available at: <pdf_path>"
  but never enumerates `images` (the page-image paths) by source page
  number, so when the LLM invents `image_path` for `inspect_region` it
  has no list to pull from. Real but small effect; fix anyway.

### What's NOT broken

- The headline run scoring, parser-bench parity, bootstrap CIs, and
  per-domain aggregation are all working as documented in the
  2026-04-29 changelog. We do not change scoring in this plan.
- FocusWorkflow itself is not changing in this sub-plan (Phase 6
  candidates 1, 5, 6 from the active plan are _separate_ sub-plans).
  The recorder change (Track A2) is additive and does not touch
  workflow logic.

## Desired End State

After this sub-plan:

1. **`results/diagnostics/headline-v1/`** contains a markdown report from
   `scripts/diagnose_predictions.py` showing per-spec breakdowns of
   tool-error rate by category, lazy-answer rate, premature-final rate,
   and iteration distribution. The "ReAct fails because of path
   hallucination" narrative is replaced in MEMORY.md with the actual
   quantified failure profile.
2. **`results/trace_viewer/<example_id>/<spec>.html`** is a self-contained
   file that opens via `file://`, renders the full trajectory of one
   prediction with crops inline, and works for all 7 specs × 4 chosen
   example IDs (28 HTML pages total).
3. **`SCHEMA_VERSION = "2"`** — `RunTrace` carries `evidence_snapshot:
list[EvidencePacketSummary] | None`. Every workflow that builds
   evidence packets snapshots them at finalize time. The migration is
   documented in MEMORY.md.
4. **Headline table refreshed.** ReAct +4 row at n=148 reflects the
   path-fairness + citation-required prompt fixes. If the change moves
   ≥ +3pp at non-overlapping CIs, the new number ships. Otherwise the
   change ships anyway as fairness hygiene with the negative result
   recorded.
5. Per-example record on disk now includes `obs_summary` and
   `confidence` for every step.

### Success criteria for the whole sub-plan

- Diagnostic report cited in a memory entry; ReAct failure profile
  matches the report (no more "ReAct hallucinates paths" as the headline
  story).
- Any reviewer can open one HTML viewer file from `file://` and see the
  full trajectory of a chosen example for a chosen method.
- Trace schema v2 lands with a migration note and existing tests stay
  green.
- ReAct +4 at n=148 has been re-run; whichever number wins ships as the
  defensible-comparator number.

## What We're NOT Doing

- **Not improving Agent baseline.** Per active-plan budget, comparator
  polish on agent baselines doesn't move FocusParse cells. Path-fairness
  changes that are inherited via `ReActAgent.__init__` propagate
  automatically; we don't tune `agent_baseline.py` further.
- **Not improving FocusWorkflow stages** in this sub-plan (no inspector
  LLM dispatch, no multi-scale packets, no chart_to_table). Those are
  separate Phase 6 candidates with their own A/Bs.
- **Not building a generic web UI.** The viewer is a single HTML file per
  prediction, openable from `file://`. No server, no React, no build
  step.
- **Not changing scoring** or aggregation. The `evidence_reward`
  formula stays. Only on-disk fields change.
- **Not blowing the schema-v2 bump up.** `evidence_snapshot` is the
  only new field; we don't bundle other "while-we're-at-it"
  changes into the same migration.
- **Not re-running every comparator at n=148.** Only ReAct +4 is
  re-run after the fix. ReAct +2 / Agent baseline don't change enough
  to justify the spend.

## Implementation Approach

Four tracks. A → B → C → D in that order. A and B can be developed in
parallel after A1+A2 land (B depends on the schema bump). C depends on A4
(diagnostic finding). Each track lands in multiple commits per
`feedback_commit_granularity.md`. Each track ends with a memory entry per
the 4-question rubric (cell / how much / mechanism / A/B + CIs).

---

## Track A: Diagnose-first

### Overview

Make on-disk traces complete enough to mine, then mine them. No new
methods, no API spend. Confirm or correct the lazy-answer hypothesis at
n=148 across all 7 specs.

### Changes Required

#### A1 — Serialize `obs_summary` + `confidence` into per-example records

**File**: `src/focusparse/eval/harness.py`
**Changes**: In `_score_and_record` (around line 843), extend the per-step
serializer to include `obs_summary` and `confidence`. They're already on
the in-memory `TrajectoryStep`; just add them to the dict comprehension
that builds `trace_dict["steps"]`.

```python
trace_dict["steps"] = [
    {
        "step_index": s.step_index,
        "stage": s.stage,
        "tier": s.tier,
        "action": s.action,
        "tool": s.tool,
        "args": s.args,
        "obs_ref": s.obs_ref,
        "obs_summary": s.obs_summary,        # NEW
        "tokens_in": s.tokens_in,
        "tokens_out": s.tokens_out,
        "latency_ms": s.latency_ms,
        "usd": s.usd,
        "confidence": s.confidence,          # NEW
    }
    for s in result.trace.steps
]
```

Also extend `record["trace"]` to carry the new top-level
`evidence_snapshot` field added in A2.

Single commit.

#### A2 — Trace schema v1 → v2: `evidence_snapshot` on `RunTrace`

**Files**:

- `src/focusparse/traces/recorder.py` — add typed `EvidencePacketSummary` and `evidence_snapshot: list[EvidencePacketSummary] | None = None` on `RunTrace`. Add `recorder.set_evidence_snapshot(packets)`.
- `src/focusparse/traces/export.py` — bump `SCHEMA_VERSION = "2"`. `trace_to_sft_record` includes `evidence_snapshot`.
- `src/focusparse/pipeline/workflow.py` — at `_run_answer` (line 665) we have `evidence` in scope. Just before `recorder.finalize`, call `recorder.set_evidence_snapshot([_summary(p) for p in evidence.packets])`.
- `src/focusparse/pipeline/react_agent.py` — at the end of `run`, snapshot whatever final tool outputs we have. ReAct doesn't build `EvidencePacket`s, so the summary uses `tool` + `args["action_input"]` + `obs_summary` for each successful tool step. Single helper.
- `configs/default.yaml` — bump `traces.schema_version` if present.

`EvidencePacketSummary` shape (subset of full packet, JSON-safe):

```python
class EvidencePacketSummary(BaseModel):
    packet_id: str
    page: int
    bbox_norm: tuple[float, float, float, float]
    region_type: str | None = None
    local_crop_ref: str | None = None
    linked_crop_refs: list[str] = Field(default_factory=list)
    text_layer_snippet: str | None = None
    ocr_snippet: str | None = None
    confidence: float = 1.0
    provenance_tool: str | None = None
```

Test additions in `tests/test_recorder.py` (extend) and
`tests/test_export.py`: schema_version bump, snapshot round-trip,
back-compat for traces with `evidence_snapshot=None`.

**Memory migration entry**: append to `.claude/memory/project_changelog.md`
documenting the bump (per `traces/export.py` docstring convention).

3 commits: recorder + tests, export + tests, workflow/react wiring.

#### A3 — `scripts/diagnose_predictions.py`

**File**: `scripts/diagnose_predictions.py` (new)
**Purpose**: walk one or more spec dirs (`predictions/*.json`), compute:

- `tool_error_rate` overall + per-error-category (`unknown_tool`, `validation_error`, `tool_runtime_error`)
- `lazy_answer_rate` = fraction of records with `answer_correct == True` but `len(citations) == 0`, AND fraction of records with `len(citations) == 0` regardless of correctness
- `premature_final_rate` for ReAct/baseline only = fraction of runs where `final_answer` was emitted with `iteration == 0`
- iteration histogram (steps with `action != "final_answer"`)
- top-5 most common `action_input` shapes per tool name
- mean tool calls / example, mean iterations used, mean USD / example
- breakdown by spec when invoked over multiple dirs

CLI:

```
uv run python scripts/diagnose_predictions.py \
  --spec-dir results/hf/headline-v1 \
  --output results/diagnostics/headline-v1/report.md
```

Markdown output mirrors `headline_table.md` style (one table per spec,
overall comparison block at top). JSON sibling for downstream tooling.

Single commit. ~200 lines of Python; pure stdlib + `json`.

#### A4 — Run A3 on existing predictions; commit memory entry

No code change. Run command above against
`results/hf/headline-v1/`. Inspect the report. Append a dated entry to
`.claude/memory/project_changelog.md` with:

- The actual ReAct failure profile (lazy %, tool-error %, premature-final %)
- Replacement for the "ReAct hallucinates paths" narrative in the
  2026-04-29 changelog entry
- The 4-question rubric for the upcoming Track C work:
  1. Cell: ReAct +4 / Overall / accuracy
  2. Expected lift: +5 to +10pp from lazy-answer fix; +0 to +1pp from path-fairness alone
  3. Mechanism: forcing tool-grounded citations should raise
     `answer_correct ∧ |citations| > 0` rate, which is the same denominator
     `score_evidence_reward` uses
  4. A/B at n=148, bootstrapped CIs, ship if non-overlapping

Single commit (memory + report).

### Success Criteria

#### Automated:

- [ ] `uv run pytest tests/test_recorder.py tests/test_export.py -v` passes the new schema-v2 cases.
- [ ] `uv run pytest` full suite stays green (482+ tests).
- [ ] `uv run ruff check src/ tests/ scripts/` passes.
- [ ] `uv run python scripts/diagnose_predictions.py --spec-dir results/hf/headline-v1 --output results/diagnostics/headline-v1/report.md` exits 0 and produces a non-empty markdown file.
- [ ] One ReAct +4 prediction JSON, when loaded post-A1, has `trace.steps[*].obs_summary` populated and `trace.evidence_snapshot` is either non-null (focus runs) or null (comparator runs that don't snapshot).

#### Manual:

- [ ] Diagnostic report's ReAct +4 row shows lazy_answer_rate > 50% and tool_error_rate < 10% (i.e. the discovery from the planning dive holds at the markdown layer).
- [ ] Memory entry replaces the path-hallucination narrative with the lazy-answer narrative and cites concrete numbers.

**Cells affected:** none directly. Sets the diagnostic floor for Track C.

---

## Track B: Single-file HTML trace viewer

### Overview

Build `scripts/visualize_trace.py` that takes `(spec_dir, example_id) →
self-contained HTML at results/trace_viewer/<example_id>/<spec>.html`.
Vanilla JS + Tailwind CDN. Crops embedded as base64. Works under
`file://`. No build step.

The viewer renders, for one trajectory:

- **Header**: question, answer_type, gold answer + bboxes, predicted
  answer + citations, `evidence_reward`, `is_lazy`, `bbox_iou`, total
  tokens, total USD.
- **Timeline**: one card per `TrajectoryStep`, color-coded by stage and
  tier, with iteration numbers.
- **Per-step expandable**: full `args`, `obs_summary`, tool input, tool
  output, tokens/USD/latency. For tool steps that produced a crop
  (LLM `inspect_region` calls in ReAct, or any FocusWorkflow step
  whose linked packets reference a crop), inline the crop image
  base64-embedded.
- **Evidence panel**: one section per `evidence_snapshot` packet:
  page number, bbox, region_type, crop image inline, text layer /
  OCR snippet, neighbor types.
- **Page-overlay panel**: gold bbox + predicted bbox(es) drawn on top
  of the relevant page image (match `smoke_visualize.py`'s overlay
  logic, ported to JS canvas).

### Changes Required

#### B1 — `scripts/visualize_trace.py`

**File**: `scripts/visualize_trace.py` (new)

CLI:

```
uv run python scripts/visualize_trace.py \
  --spec-dir results/hf/headline-v1/focusparse_focus_agentic_multi_page_7d4b816d \
  --example-id dat-AN040_EN-0008 \
  --output results/trace_viewer/dat-AN040_EN-0008/focus_full.html
```

Internals:

1. Load `predictions/<id>.json`. Pull `trace`, `citations`, scoring fields.
2. Resolve crop refs: walk `cache/crops/`, `<spec_dir>/crops/`,
   `<spec_dir>/tiles/`, and any path referenced inside `args`. For
   `evidence_snapshot[*].local_crop_ref` and `linked_crop_refs`, base64-encode the PNG.
3. Resolve page images: pull from the staging dir
   (`~/.cache/focusparse/hf_staging/`) keyed by example_id +
   page number. Base64-encode for inline overlay rendering.
4. Render via a single Python f-string template (or Jinja-lite hand-rolled
   format) that injects the data as one `const TRACE = {...};` JSON blob
   and one `<script>` block of vanilla rendering JS. Tailwind via CDN
   (`<script src="https://cdn.tailwindcss.com"></script>` — fine for
   `file://`). One file, ~600-800 lines.

Helper module: `src/focusparse/traces/viewer.py` (new) — pure functions
for resolution + base64 encoding so they can be unit-tested.
`scripts/visualize_trace.py` is a thin CLI shim around it.

3 commits: viewer module + tests, visualize_trace CLI, page-overlay JS
canvas piece.

#### B2 — `scripts/visualize_examples.py`

**File**: `scripts/visualize_examples.py` (new)

Picks 4 example IDs spanning failure modes by mining `headline-v1`'s
`per_example.jsonl` per spec:

1. `correct_by_focus_only` — Our harness +4 correct; Base VLM wrong.
2. `correct_by_base_only` — Base VLM correct; Our harness +4 wrong.
3. `correct_by_react_not_base` — ReAct +4 correct; Base VLM wrong (rare,
   instructive when present; skip if no example matches).
4. `wrong_by_everyone` — All 7 specs wrong.

Picks deterministically (seed=42, prefers domain coverage so we get at
least 1 datasheet + 1 finance per category when possible). For each
picked ID, emits all 7 spec viewers via B1, plus an
`index.html` that links them in a 7-column comparison view per ID.

CLI:

```
uv run python scripts/visualize_examples.py \
  --headline-dir results/hf/headline-v1 \
  --output-dir results/trace_viewer/
```

Output structure:

```
results/trace_viewer/
├── index.html                                 # 4-row × 7-col grid
├── correct_by_focus_only_<id>/
│   ├── simple.html
│   ├── react_2.html
│   ├── react_4.html
│   ├── agent_baseline_2.html
│   ├── agent_baseline_4.html
│   ├── focus_2.html
│   └── focus_4.html
├── correct_by_base_only_<id>/...
├── correct_by_react_not_base_<id>/...
└── wrong_by_everyone_<id>/...
```

Single commit.

#### B3 — Tests

**File**: `tests/test_viewer.py` (new)

- Fixture: a synthetic `RunTrace` with two steps (one tool_call with a
  fake crop_ref pointing at a tiny test PNG, one final_answer). Assert
  the rendered HTML string contains the expected base64 prefix and the
  question text.
- Crop resolution: given a synthetic `cache/crops/` with one PNG
  matching a sha256 prefix, the resolver returns its bytes.
- Page-image resolution falls back to None gracefully when the staging
  dir doesn't have the page.

**File**: `tests/test_visualize_examples.py` (new)

- Fixture: 4 fake `per_example.jsonl` files (one per spec) in a temp
  dir. Assert `pick_examples` returns the expected 4 IDs.
- The `--output-dir` is populated with the expected directory tree.

Single commit per test file.

### Success Criteria

#### Automated:

- [ ] `uv run pytest tests/test_viewer.py tests/test_visualize_examples.py -v` passes.
- [ ] `uv run python scripts/visualize_trace.py --spec-dir results/hf/headline-v1/focusparse_focus_agentic_multi_page_7d4b816d --example-id <some-id> --output /tmp/viewer.html` produces a non-empty HTML file (>20 KB).
- [ ] `uv run python scripts/visualize_examples.py --headline-dir results/hf/headline-v1 --output-dir results/trace_viewer/` exits 0 and writes 28 + 1 HTML files (4 IDs × 7 specs + index.html).

#### Manual:

- [ ] Open `results/trace_viewer/index.html` from `file://` in a browser. The 4-row × 7-col grid renders. Each cell links to the spec viewer.
- [ ] Open one focus +4 viewer. Crops render inline (no broken images). Page-overlay panel shows gold bbox + predicted bbox visibly correctly aligned on the right page.
- [ ] Open one ReAct +4 viewer. The lazy-answer pattern is visually obvious (≥1 tool call but final citations empty).
- [ ] No external network requests except Tailwind CDN.

**Cells affected:** none. This is debugging surface.

---

## Track C: Improve ReAct (medium scope: path-fairness + citation-required prompt)

### Overview

Per user decision (planning conversation 2026-05-04), scope is **medium**:
the path-fairness fix (C1) + sharpened citation-requiring system prompt
(C2). C3/C4 (loop-level guards, tool-error feedback re-injection) are
out of scope to avoid reviewer pushback that we tuned the comparator.

A/B at n=148 ReAct +4 only. ReAct +2 uses the same code path so the fix
applies to both, but we don't re-run +2 (not enough cell movement
expected to justify the spend).

### Changes Required

#### C1 — Path enumeration in `_initial_user_turn`

**File**: `src/focusparse/pipeline/react_agent.py:267-283`

Replace the current vague intro:

```python
def _initial_user_turn(...):
    parts = [f"Question: {example.question}"]
    ...
    if pdf_path is not None:
        parts.append(f"PDF available at: {pdf_path}")
    if images:
        parts.append(
            f"You are shown {len(images)} image(s). Use tools to inspect ..."
        )
```

with concrete enumeration:

```python
def _initial_user_turn(...):
    parts = [f"Question: {example.question}"]
    domain = getattr(example, "domain", None)
    if domain is not None:
        parts.append(f"Domain: {str(domain).split('.')[-1].lower()}")
    if pdf_path is not None:
        parts.append(f"PDF path (use this string verbatim for `doc_path` args): {pdf_path}")
    if images:
        parts.append("Available page images (use these strings verbatim for `image_path` args):")
        for img in images:
            page = _page_number_from_filename(img.name)
            page_str = f" (page {page})" if page is not None else ""
            parts.append(f"  - {img}{page_str}")
        parts.append(
            "Cite source page numbers from this list, not positional indices. "
            "Tool inputs that reference doc_path or image_path MUST be one of "
            "the strings listed above; the runner will reject any other path."
        )
    return "user: " + "\n".join(parts)
```

Reuse `_page_number_from_filename` from `workflow.py` (currently
private) — extract to a small shared helper module
`src/focusparse/pipeline/_page_filename.py` or import directly.

Single commit.

#### C2 — Citation-requiring system prompt

**File**: `src/focusparse/pipeline/react_agent.py:50-58`

Replace:

````python
_REACT_SYSTEM_PROMPT = (
    "You are a document-parsing agent answering a question about a PDF. "
    "Each turn, output STRICT JSON in one of two shapes:\n"
    '  {"thought": "...", "action": "<tool_name>", "action_input": {...}}\n'
    '  {"thought": "...", "final_answer": "...", "citations": [{"page": N, "bbox": [x0,y0,x1,y1]}]}\n'
    "Citations use normalized [0,1] bbox coordinates. When you have enough "
    "evidence, emit `final_answer`. Do not add extra keys. Do not wrap in "
    "markdown other than a single ```json fence."
)
````

with the citation-required variant:

````python
_REACT_SYSTEM_PROMPT = (
    "You are a document-parsing agent answering a question about a PDF. "
    "Each turn, output STRICT JSON in one of two shapes:\n"
    '  {"thought": "...", "action": "<tool_name>", "action_input": {...}}\n'
    '  {"thought": "...", "final_answer": "...", "citations": [{"page": N, "bbox": [x0,y0,x1,y1]}]}\n'
    "Citations use normalized [0,1] bbox coordinates against the source page. "
    "BEFORE emitting `final_answer`, you MUST call at least one tool and "
    "include at least one citation pointing to the region of the page that "
    "supports your answer. If after using tools you still cannot find a "
    "supporting region, answer the literal string 'Unanswerable' with an "
    "empty citations list — do not guess. Do not add extra keys. Do not "
    "wrap in markdown other than a single ```json fence."
)
````

This is **prompt-only** — no loop changes. The model can still violate
the contract (and the parser will accept whatever it returns); we are
just clarifying the expected shape. C3 (loop-level enforcement) is out
of scope.

`AgentBaselineAgent` inherits this via `_system_prompt`'s overridable
hook. The baseline keeps its generic prompt
(`_AGENT_BASELINE_SYSTEM_PROMPT` in `agent_baseline.py:36-41`)
**unchanged** — that's deliberate per the active plan ("the two
comparator rows differ in prompt-effort budget").

Single commit.

#### C3 — Re-run ReAct +4 at n=148

After C1 + C2 land, invalidate cached predictions for the ReAct +4 spec
and re-run.

```bash
rm -rf results/hf/headline-v1/focusparse_react_agentic_multi_page_*tool_set=full*/predictions/

uv run python scripts/run_hf_eval.py \
  --agent react --tool-set full \
  --protocol agentic_multi_page \
  --output-dir results/hf/headline-v2/react-fix-arm \
  --staging-dir ~/.cache/focusparse/hf_staging \
  --pdfs-root ~/.cache/focusparse/pdfs \
  --no-resume
```

Estimated cost: ~$2 at n=148 (ReAct +4 averaged ~$1.5 in the headline
run; might rise slightly because longer prompts and possibly more tool
calls per example).

Then re-render the headline table: copy-merge the ReAct +4 cell from
`headline-v2/react-fix-arm` into a new merged
`results/hf/headline-v2/headline_table.json`, keeping all other 6 cells
from `headline-v1`. Re-render markdown + HTML via
`scripts/render_headline_table.py`.

Single commit (just the re-run artifacts; no code change).

#### C4 — Memory entry + decision

Append a dated entry to `.claude/memory/project_changelog.md`:

- **Cell:** `ReAct +4 / Overall / accuracy` (and per-domain).
- **Move:** new vs. old number with bootstrap CIs.
- **Mechanism:** path-enumeration removed `tool_error` confound;
  citation-required prompt cut lazy-answer rate.
- **Decision rule:**
  - If new accuracy is ≥ old +3pp at non-overlapping CIs: ship the
    headline-v2 table as canonical. Note that the comparator gap claim
    is _narrower_ but still defensible.
  - If new accuracy is between old and old +3pp: ship the fix
    anyway (it's correctness/fairness), record the smaller gap, note
    that the bigger lift would require C3/C4 which are out of scope.
  - If new accuracy is _lower_ than old: ship anyway (we can't ship a
    headline that depends on a comparator's bug to look good), record
    the negative result, and the comparator-gap claim shrinks
    accordingly.

The memory entry honestly states which of the three cases occurred.

Single commit.

### Success Criteria

#### Automated:

- [ ] `uv run pytest tests/test_react_agent.py -v` passes after the prompt change (existing 15 tests + any new prompt-shape assertion).
- [ ] `uv run ruff check src/focusparse/pipeline/` passes.
- [ ] `uv run python scripts/run_hf_eval.py --agent react --tool-set full --protocol agentic_multi_page --limit 5 --no-resume ...` completes against a tiny smoke set without runtime errors.
- [ ] Re-rendered headline table at `results/hf/headline-v2/headline_table.{json,md,html}` has all 28 cells populated and bootstrap CIs.

#### Manual:

- [ ] Spot-check 5 ReAct +4 traces from the new run via the Track B viewer. Lazy-answer rate visibly down: at least 3/5 have non-empty citations.
- [ ] Memory entry honestly states the three-way decision outcome above.
- [ ] No regression in `simple/full_doc` reproducibility gate (ReAct fix doesn't touch the simple agent; gate should be untouched, but verify by re-rendering the `repro` row in the new headline).

**Cells affected:** ReAct +4 (Datasheets / Finance × accuracy / $/correct = 4 cells).

---

## Track D: Memory + headline-table ship

### D1 — One consolidated memory entry per track

Already covered in A4 / B (no entry needed; visualization tooling) / C4.
Track B does NOT get a 4-question rubric entry — visualization tooling
isn't a cell-mover. Instead, append a short "viewer shipped" note to
`project_changelog.md` so future agents know it exists and how to invoke
it.

### D2 — Update active plan's "Phase 6 candidates" list

**File**: `plans/2026-04-29-research-driven-eval-framework.md`
**Changes**: Add a one-line entry above the existing Phase 6 candidates
list noting that this sub-plan landed and which candidates it covered
(none of the original 9 — this is comparator hygiene + tooling). No
re-prioritization.

Single commit.

### D3 — Update CLAUDE.md if a load-bearing contract changed

The trace `SCHEMA_VERSION` bumped 1 → 2. CLAUDE.md says:

> `src/focusparse/traces/export.py::SCHEMA_VERSION` — interface with the future FocusTrain repo. Bump on any field change and log the migration in `.claude/memory/MEMORY.md`.

The migration log lives in `project_changelog.md` (per A4); CLAUDE.md
itself doesn't need to change because it points at `SCHEMA_VERSION`
generically, not a specific number. **Verify** during the implementation
that CLAUDE.md still reads correctly. No change expected.

---

## Testing Strategy

### Unit Tests (new or extended)

- `tests/test_recorder.py` — `evidence_snapshot` field round-trip; legacy traces with `evidence_snapshot=None` still serialize.
- `tests/test_export.py` — `SCHEMA_VERSION == "2"`; record shape matches; back-compat unmarshal of v1 records (read-only).
- `tests/test_react_agent.py` — system-prompt regression assertion for the citation-required clause; `_initial_user_turn` enumerates each image path verbatim.
- `tests/test_viewer.py` (new) — synthetic trace → HTML string contains expected base64 + question text; crop-resolver round-trip.
- `tests/test_visualize_examples.py` (new) — `pick_examples` deterministic; `--output-dir` populated.
- `tests/test_diagnose_predictions.py` (new) — synthetic predictions dir → expected counts; markdown output schema.

### Integration Tests

- Run `scripts/run_hf_eval.py --agent react --tool-set full --limit 3 --no-resume` against staging fixtures; assert the resulting per-example records carry `obs_summary`, `confidence`, and (for focus runs) `evidence_snapshot`.

### Manual Testing Steps

1. After Track A: run `scripts/diagnose_predictions.py --spec-dir results/hf/headline-v1`; eyeball the report; the lazy-answer narrative should hold.
2. After Track B: open `results/trace_viewer/index.html` from `file://`; click into 1 cell per row; visually confirm crops render and page overlays are aligned.
3. After Track C re-run: spot-check 5 viewers from the new ReAct +4 dir; lazy-answer rate visibly down.

## Performance Considerations

- **Diagnostic script**: pure local file I/O over ~1000 JSON files; <30s wall.
- **Viewer**: per-prediction HTML 200-500 KB after base64 inlining (typical 5-10 crops × 30-100 KB each). 28 HTMLs = ~10 MB total. Acceptable for local viewing.
- **Re-run cost**: ~$2 for ReAct +4 at n=148. Within the $5 budget.
- **Schema bump**: existing per-example records (v1) stay readable for the diagnostic script (lacks new fields → defaults to None / absent). New runs go to v2.

## Migration Notes

- **Trace schema v1 → v2**: `evidence_snapshot` is the only new field on `RunTrace`. Existing JSONL exports remain valid v1 records and will continue to be loadable by FocusTrain consumers; downstream tooling should not assume `evidence_snapshot` is present unless `schema_version == "2"`.
- **Cached predictions in `headline-v1/`**: keep as-is. The diagnostic in A4 reads them directly. The Track C re-run lands in `headline-v2/react-fix-arm/` so we can compare cleanly.
- **`per_example.jsonl`** changes shape (gains `obs_summary` + `confidence` per step + optional `evidence_snapshot`). Anything downstream (the renderer in `scripts/render_headline_table.py`) reads `aggregate_by_domain`, not per-step fields, so it's safe.

## References

- **Active plan**: `plans/2026-04-29-research-driven-eval-framework.md` (Phase 6).
- **Handoff**: `thoughts/shared/handoffs/general/2026-05-04_11-35-53_focusparse-headline-table-next-steps.md`. _Note: the handoff's path-hallucination diagnosis is partially incorrect; this plan's Track A4 supersedes it._
- **Headline-v1 artifacts**: `results/hf/headline-v1/headline_table.{json,md,html}` and per-spec `predictions/`.
- **Standing context**: `.claude/memory/MEMORY.md` "Research framework" + "Narrowed scope" sections.
- **Trace recorder**: `src/focusparse/traces/recorder.py`, `src/focusparse/traces/export.py` (load-bearing per CLAUDE.md).
- **Comparator scaffolding**: `src/focusparse/pipeline/react_agent.py`, `src/focusparse/pipeline/agent_baseline.py`.
- **Existing visualization prior art**: `scripts/smoke_visualize.py` (console-only).
