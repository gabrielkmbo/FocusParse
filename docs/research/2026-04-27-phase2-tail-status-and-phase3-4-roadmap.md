---
date: 2026-04-27T14:34:00-07:00
researcher: Gabriel Bo
git_commit: 43f933ec424d1aeb31f09c893068ff0db1ee6e06
branch: main
repository: FocusParse
topic: "Phase 2 SOTA-leverage tail status + Phase 3/4 roadmap"
tags: [research, phase-2, phase-3, phase-4, workflow, eval, tools, roadmap]
status: complete
last_updated: 2026-04-27
last_updated_by: Gabriel Bo
---

# Research: Phase 2 SOTA-leverage tail status + Phase 3/4 roadmap

**Date**: 2026-04-27 14:34 PDT
**Researcher**: Gabriel Bo
**Git Commit**: `43f933e` (`main`)
**Repository**: FocusParse

## Research Question

What's shipped in the Phase 2 SOTA-leverage tail (items 1-5 of `plans/2026-04-27-phase2-sota-leverage.md`), what's still in the queue (items 4-5 + Phase 4+ scope-shift items), and what's the concrete files-to-touch work order for Phase 3 (Tools layer) + Phase 4 (Eval/HTML report)?

## Summary

**Phase 2 tail is 3/5 complete.** Items 1 (page-score fix), 2 (stage-level metrics + `diff_runs.py` gate), and 3 (verifier→retry control flow) all shipped on 2026-04-27 with measurable deltas captured. Items 4 (query-conditioned region reranker) and 5 (evidence-graph expansion) are queued behind the multi-example A/B currently running on 30 validation examples to prove item 3's loop helps in aggregate (n=1 smoke was inconclusive).

**Phase 3 (Tools layer)** has 3/5 tools real (`inspect_region` / `get_text_layer` / `layout_detect`) and 2 stubs (`run_python` / `chart_to_table`). The full `inspect_region` is 374 lines with 3 modes; the two stubs raise `NotImplementedError` with TODO markers.

**Phase 4 (Eval + HTML report)** has the scoring layer real (`stage_metrics.py` + `diff_runs.py` already shipped, originally Phase-4 work pulled forward) but `eval/report.py::render_run_report` is a 14-line stub. Per-stage diff harness exists; what's missing is the human-facing HTML rendering with bbox overlays + trajectory tables.

**Top-level test count**: 340 passing (one skipped for HF streaming, one deselected pre-existing failure). Suite has grown 285 → 332 → 340 across items 1, 2, 3.

## Detailed Findings

### 1. Phase 2 SOTA-leverage tail — what shipped (items 1-3)

#### Item 1: Page-score zeroing fix (3 commits, 2026-04-27)

Decoupled `region.score` from `pc.score` so single-document FTS5 BM25 = 0.0 doesn't zero every region. Page routing signal preserved in `supporting_signals`.

- `src/focusparse/pipeline/localizer.py:160-176` — `signals = ["layout_detect", f"page_routing={pc.reason_code}"]`; `score=float(det.score)` (was `float(pc.score) * float(det.score)`)
- `src/focusparse/pipeline/localizer.py:179-200` — `_skeleton_region` also stamps `page_routing=<reason_code>`
- `tests/test_localizer.py:319-389` — 2 new regression tests (`test_propose_regions_score_independent_of_page_score`, `test_skeleton_region_records_page_routing_signal`) covering pc.score=0.0 propagation
- Verified end-to-end: 14 region scores went from all 0.000 → 0.538-0.969 on the smoke

#### Item 2: Stage-level metrics + `diff_runs.py` (7 commits, 2026-04-27)

Pulled forward from Phase 4 per the user directive: items 3-5 don't ship without measurable A/B deltas, so metrics are the gate.

- `src/focusparse/eval/stage_metrics.py:1-630` (new) — pure-function `compute_stage_metrics(record, example, image_dims_by_page) -> StageMetrics`
  - `RoutingMetrics` (line ~37): page_recall@{1,3,5} + page_precision@5 + pages_inspected
  - `LocalizationMetrics` (line ~46): region_recall (≥50% coverage) + region_precision + bbox_iou_max + lazy_full_page_rate (>60% area) + duplicate_crop_rate (IoU>0.7)
  - `EvidenceMetrics` (line ~57): cited_evidence_completeness + expansion_useful_rate (both `None` placeholders — populated by item 5)
  - `ReasoningMetrics` (line ~67): answer_correct + is_abstention (keyword detect) + is_correct_abstention + verifier_caught_unsupported
  - `LoopMetrics` (line ~73): loop_retries + loop_terminated + loop_retry_helped
  - `StageEfficiency` per-stage: tokens / usd / latency / tool_calls (summed across multi-step instances)
  - `aggregate_stage_metrics` (line ~336): mean of floats, rate of bools, sum-mean of efficiency, distribution of loop_terminated; None values excluded
- `src/focusparse/eval/harness.py:401-505` — `_score_and_record` flattens `result.trace.steps` to a plain dict, copies telemetry, attaches `record["stages"]`
- `src/focusparse/eval/harness.py:540-562` — `_aggregate_stages` rehydrates per-example StageMetrics blocks → writes `stage_aggregate` to `run.json`. Legacy cached predictions (no `stages`) fall through to default StageMetrics
- `scripts/diff_runs.py:1-313` (new) — A/B harness, reads two run.json files, prints stage-by-stage deltas with direction labels (↑good / ↓bad / ↑bad / ↓good for lower-is-better metrics, tradeoff for efficiency / retries). `--format json` for CI piping.
- `tests/test_stage_metrics.py` (32 tests) + `tests/test_diff_runs.py` (12 tests) + 3 added to `tests/test_focus_harness.py`
- Reference baseline saved at `results/hf/baseline-after-item2/focusparse_focus_focus_default_7d4b816d/run.json` (n=1, `dat-Arm_EE382N_4-0001`, with PDF). Item 3 diffs against this.

#### Item 3: Verifier→retry control-flow loop (4 commits, 2026-04-27)

The verifier finally acts as a controller. `FocusWorkflow.run` consumes `verdict.next_action` and re-enters the appropriate stages.

- `src/focusparse/pipeline/workflow.py:69-95` — `FocusWorkflow.__init__` gains `max_retries: int = _DEFAULT_MAX_RETRIES` (default 2; `0` disables the loop and restores pre-loop cascade)
- `src/focusparse/pipeline/workflow.py:144-411` — `run()` rewritten with refactored stage helpers + retry loop
  - Loop body at lines ~262-407: dispatches per `verdict.next_action`
    - `accept` → break, `loop_terminated="accepted"`
    - `abstain` → answer = "Unanswerable", break, `loop_terminated="abstained"`
    - `retry_localization` → re-runs `_run_localize` + `_run_inspect` + `_run_expand` (regions changed → packets stale); tightens `confidence_threshold` by `_LOCALIZATION_RETRY_FACTOR=0.7`
    - `expand_context` → re-runs only `_run_expand`; widens `adjacency_pad` by `_EXPAND_RETRY_FACTOR=1.5` (capped at `_MAX_ADJACENCY_PAD=0.30`)
    - `escalate_reasoner` → re-runs only `_run_answer` + `_run_verify` with `escalation_hint=verdict.reason`
    - unknown action → break as "accepted" (don't thrash)
  - `else` branch on `while` (line ~404): runs when retries exhausted → `loop_terminated="exhausted"`
- `src/focusparse/pipeline/workflow.py:417-617` — 5 new private async helpers: `_run_localize`, `_run_inspect`, `_run_expand`, `_run_answer`, `_run_verify`. Each takes `recorder` + `step_counter` + `retry_attempt: int = 0` and records one TrajectoryStep with `args["retry_attempt"]`
- `src/focusparse/pipeline/workflow.py:623-637` — new `_StepCounter` replaces hardcoded `step_index=0..6`
- `src/focusparse/pipeline/reasoner.py:32-50` — `answer_from_evidence(escalation_hint=None)` prepends the verifier's reason to the prompt when set; backwards compat (None on first attempts)
- Telemetry on `WorkflowResult.telemetry`: `retries_used` (int), `loop_terminated` (str), `loop_retry_helped` (bool|None)
- `tests/test_workflow.py:393-756` — 8 new loop tests (one per path) + `_ScriptedClient` helper that yields a sequence of responses
- Real-document A/B (n=1, `dat-Arm_EE382N_4-0001`): loop fired 2 retries, `loop_terminated=exhausted`, `retry_helped=False`, answer still wrong, +200% answer tokens. **n=1 is inconclusive — multi-example A/B in progress as of 2026-04-27 14:33 (8/30 examples done).**

### 2. Phase 2 SOTA-leverage — NOT yet shipped

#### Item 4: Query-conditioned region reranker

Plan at `plans/2026-04-27-phase2-sota-leverage.md:176-203`. Status: NOT STARTED.

- `src/focusparse/pipeline/region_reranker.py` (new) — needs creating. New stage between `propose_regions` and `inspect_regions`.
- `src/focusparse/pipeline/events.py` — extend `RegionCandidate` with optional `relevance: float` and `needed_for: str | None`
- `src/focusparse/pipeline/workflow.py` — insert rerank call after `_run_localize` (line ~213 area), record TrajectoryStep
- `tests/test_region_reranker.py` (new)
- Uses already-configured `localizer_rerank: mid` tier in `configs/default.yaml`
- Skip path: `tier_router=None` → no-op (preserves existing tests)

#### Item 5: Evidence-graph expansion

Plan at `plans/2026-04-27-phase2-sota-leverage.md:206-240`. Status: NOT STARTED.

- `src/focusparse/pipeline/evidence_graph.py` (new) — typed graph: `chart→{legend, x_axis, y_axis, footnote, caption, title}`, `table_row→{column_header, condition_note, unit_row}`, `spec_value→{unit_note, package_constraint}`, etc.
- `src/focusparse/pipeline/expander.py:48-65` — current `_NEIGHBOR_TYPES` set is the spatial-only baseline; needs replacement with graph walker, keeping spatial heuristic as fallback for unknown types
- `tests/test_evidence_graph.py` (new) + extensions to `tests/test_expander.py`
- Inference-time only: parser-bench's gold `evidence_relations` field is training data, not visible at inference (but useful for validating the heuristic)

#### Phase 4+ items reopening frozen stages (need scope-shift conversation)

From `.claude/memory/project_roadmap.md` and the user's 12-item list:

- **#2 Page Navigator with visual recall** — replaces FTS-only routing with FTS ∪ OCR-summary ∪ visual-embedding ∪ thumbnail-VLM-sample union (DocLens-style). Reopens `route_pages` (currently frozen).
- **#8 Answer sampler + adjudicator** — generate N candidates via reasoner, adjudicate. Reopens `answer` (frozen).
- **#9 Unanswerable protocol with failure_type** — verifier emits typed failures (`missing_evidence` / `conflicting_evidence` / `unreadable_crop` / `insufficient_context`) + `required_next_evidence`. Reopens `verify` (frozen).
- **#11 Learned tool policy** — SFT/GRPO on trajectories. Lives in future FocusTrain repo.
- **#12 Hard-negative mining loop** — auto-mine bad traces into training examples. FocusTrain.

### 3. Phase 3 (Tools layer) — concrete work order

Status: 3/5 tools real, 2 stubs.

| Tool             | File                                     | Status   | LOC | Notes                                                                                              |
| ---------------- | ---------------------------------------- | -------- | --- | -------------------------------------------------------------------------------------------------- |
| `inspect_region` | `src/focusparse/tools/inspect_region.py` | **Real** | 374 | 3 modes (image/element/region); content-addressed cache                                            |
| `get_text_layer` | `src/focusparse/tools/get_text_layer.py` | **Real** | 214 | PyMuPDF native + bbox filter; cache                                                                |
| `layout_detect`  | `src/focusparse/tools/layout_detect.py`  | **Real** | 280 | HF RT-DETRv2 client; retry + stub detection                                                        |
| `expand_context` | `src/focusparse/tools/expand_context.py` | **Stub** | 25  | NotImplementedError; the workflow's `expander.py` does the real work directly via `inspect_region` |
| `run_python`     | `src/focusparse/tools/run_python.py`     | **Stub** | 68  | `RunPythonInput` schema + ALLOWED_IMPORTS list; needs subprocess + rlimit + allowlist              |
| `chart_to_table` | `src/focusparse/tools/chart_to_table.py` | **Stub** | 28  | gated behind `[chart-tools]` extra                                                                 |

Recommended Phase 3 work order (dependency-aware):

1. **`run_python` sandboxed image workbench** (gates LLM-driven inspector loop = sub-phase 2g step 2)
   - Implement `_run_child` with `multiprocessing.Process` + `resource.setrlimit(RLIMIT_CPU, 15)` + `RLIMIT_AS, 1024MB`
   - Import allowlist enforced via `sys.modules` whitelist in the child (`ALLOWED_IMPORTS` set already defined, file `src/focusparse/tools/run_python.py:30-49`)
   - Image refs passed as content-addressed keys; child resolves to bytes via cache
   - Output: stdout + optional new image (assigned new ref), stored as `obs_ref` for the trajectory
   - Tests: timeout kill, import-denied (`os.system`), normal crop+resize round trip
   - File: `src/focusparse/tools/run_python.py` (replace stub)
   - New: `tests/test_run_python.py`

2. **Multi-scale crop packets** (item #5 from user's SOTA list)
   - `src/focusparse/evidence/packet.py` already has the slots: `page_thumbnail_ref`, `local_crop_ref`, `context_crop_ref`, `linked_crop_refs`
   - `src/focusparse/pipeline/inspector.py:84-225` (`_inspect_one_region`) currently sets only `local_crop_ref`. Add: render context crop (medium DPI, +20% pad), keep local crop tight, populate `context_crop_ref`
   - Reasoner prompt at `src/focusparse/pipeline/reasoner.py:43-50` should reference both `local_crop_ref` and `context_crop_ref` so the VLM gets the zoom hierarchy
   - Tests: extend `tests/test_inspector.py` for multi-scale packet shape

3. **Chart specialist** (`inspect_chart`) (item #7)
   - New file: `src/focusparse/tools/inspect_chart.py` — structured output `{chart_type, series, x_axis, y_axis, unit, candidate_values, supporting_regions}`
   - Routed by inspector when `region_type == "chart"` AND `figure_class in {bar_chart, line_chart, ...}`
   - Implementation options: (a) cheap-tier VLM with structured prompt; (b) `run_python` + numpy peak detection; (c) hybrid
   - Tests: `tests/test_inspect_chart.py` covering each chart type
   - File: `src/focusparse/pipeline/inspector.py` — add `chart`-mode dispatch

4. **Table specialist** (`inspect_table`) (item #7)
   - New file: `src/focusparse/tools/inspect_table.py` — structured output `{rows, columns, cells, header_row_idx, condition_note}`
   - Routed when `region_type == "table"`
   - Likely path: `run_python` + heuristic gridline detection + per-cell OCR
   - File: `src/focusparse/pipeline/inspector.py` — add `table`-mode dispatch

5. **`chart_to_table` (deferred — gated by `[chart-tools]` extra)** — already stubbed; pursue only if Phase 5 LlamaParse baseline shows finance-chart accuracy gap that specialists can close

#### Cache layer (already mostly in place)

- `src/focusparse/cache/store.py` — content-addressed cache shared across tools (existing)
- Each tool already content-addresses its outputs:
  - `inspect_region.py:296-318` — `_crop_cache_key(pdf_path, page, bbox, mode, dpi, rotation, expansion)`
  - `get_text_layer.py:191-202` — `_cache_key(pdf_path, page, bbox)`
  - `layout_detect.py:259-265` — `_cache_key(endpoint, png_bytes)`
- Per-doc cache root: `<config.cache.root>/{layout,crops,text_layer,text_index}/`

### 4. Phase 4 (Eval + HTML report) — concrete work order

Status: scoring + diff harness real (pulled forward as item 2); HTML report stub.

| Component                        | File                                   | Status                                                                                                    |
| -------------------------------- | -------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Scoring with lazy-answer penalty | `src/focusparse/eval/scoring.py`       | **Real** (4 functions: `score_answer`, `page_recall`, `max_iou_over_alternates`, `score_evidence_reward`) |
| Aggregate metrics                | `src/focusparse/eval/metrics.py:15-56` | **Real** (`AggregateMetrics` + `aggregate()`)                                                             |
| Stage-level metrics              | `src/focusparse/eval/stage_metrics.py` | **Real** (item 2)                                                                                         |
| Diff harness                     | `scripts/diff_runs.py`                 | **Real** (item 2)                                                                                         |
| HTML report                      | `src/focusparse/eval/report.py`        | **Stub** (14 lines, `render_run_report` raises NotImplementedError)                                       |
| `focus report` CLI               | `src/focusparse/cli/focus.py:303-309`  | **Wired but raises** (calls `render_run_report` which is unimplemented)                                   |

Recommended Phase 4 work order:

1. **`render_run_report(run_dir) -> Path` index page**
   - Jinja2 template (already in dev-extras via `pyproject.toml`)
   - Reads `run.json` (manifest + aggregate + stage_aggregate) + `per_example.jsonl`
   - Top-level table: per-example row with question / pred / gold / answer_correct / bbox_iou / cost
   - Aggregate row: accuracy, evidence_reward_mean, lazy_answer_rate, abstention_rate, usd_per_correct
   - Stage breakdown table (from `stage_aggregate`): per-stage routing/localize/inspect/expand/answer/verify metrics + efficiency
   - Stretch: per-family / per-stress_type breakdown (planned at `eval/metrics.py:3-4` TODO comment)
   - File: `src/focusparse/eval/report.py` (replace stub)
   - File: new `src/focusparse/eval/templates/index.html.j2`

2. **Per-example pages with bbox overlays**
   - Render one HTML page per example with:
     - Page thumbnails (`page_image_ref` from packets)
     - Gold bboxes (green) + predicted bboxes (red) + inspected crop bboxes (orange)
     - Coordinate-space normalization handled (use `image_dims_by_page` like scoring does)
     - Trajectory table: stage / tier / action / args / tokens / latency / cost
     - Loop indicators when retries fired (`retry_attempt` from step args, `loop_terminated` from telemetry)
   - Pattern source: `scripts/smoke_visualize.py:_draw_bbox_overlays` (lines ~134-200) — already does the gold/pred overlay logic for the smoke; lift the math
   - File: new `src/focusparse/eval/templates/example.html.j2`

3. **Stage-level diff visualization (stretch)**
   - HTML version of `scripts/diff_runs.py` table — useful when comparing two runs in the report
   - File: new `src/focusparse/eval/templates/diff.html.j2`
   - Optional, but pairs nicely with the multi-example A/B sweeps items 3-5 will produce

4. **Spot-check tooling for the manual verification step in `plans/2026-04-13-focusparse-agentic-pipeline.md:741-744`**
   - "Spot-check 3 lazy-answer examples: the HTML clearly shows the penalty and why" — needs the lazy_full_page flag visible in the per-example page
   - "Spot-check 3 high-reward examples: gold + predicted bboxes overlap visibly" — needs the overlay rendering

5. **Tests**
   - `tests/test_report.py` (new) — golden-HTML test against a fixture run directory
   - Snapshot test: parse the rendered HTML with BeautifulSoup, assert key cells are present (gold answer, pred answer, IoU, retries, lazy flag)

## Code References

### Phase 2 tail entry points

- `src/focusparse/pipeline/workflow.py:144` — `FocusWorkflow.run` (the loop lives here)
- `src/focusparse/pipeline/workflow.py:262-407` — retry loop body
- `src/focusparse/pipeline/workflow.py:417-617` — 5 stage helpers (`_run_localize`, `_run_inspect`, `_run_expand`, `_run_answer`, `_run_verify`)
- `src/focusparse/pipeline/localizer.py:160-176` — decoupled scoring (item 1 fix)
- `src/focusparse/eval/stage_metrics.py:99-140` — `compute_stage_metrics` per-example
- `src/focusparse/eval/stage_metrics.py:336-435` — `aggregate_stage_metrics`
- `scripts/diff_runs.py:59-79` — A/B CLI entry
- `src/focusparse/eval/harness.py:540-562` — `_aggregate_stages` (legacy resume safe)

### Phase 3 work entry points

- `src/focusparse/tools/run_python.py:60-68` — `run_python` stub (NotImplementedError)
- `src/focusparse/tools/run_python.py:30-49` — `ALLOWED_IMPORTS` set already defined
- `src/focusparse/tools/chart_to_table.py:24-28` — chart specialist stub
- `src/focusparse/tools/expand_context.py:21-25` — orphan stub (workflow's `expander.py` does the work)
- `src/focusparse/pipeline/inspector.py:84-225` — `_inspect_one_region` (where multi-scale + chart/table dispatch lands)
- `src/focusparse/pipeline/reasoner.py:43-50` — prompt (where multi-scale ref hierarchy goes)

### Phase 4 work entry points

- `src/focusparse/eval/report.py:8-14` — `render_run_report` stub
- `src/focusparse/cli/focus.py:303-309` — `focus report <run_dir>` CLI command (calls the stub)
- `scripts/smoke_visualize.py:134-200` — bbox overlay logic to lift into the templates
- `src/focusparse/eval/metrics.py:3-4` — TODO comment for per-family/stress_type breakdown

## Architecture Documentation

### Pipeline shape (post-item-3)

```
plan → route_pages → localize → inspect → expand_context → answer → verify
                        ↑          ↑           ↑                       ↓
                        └─ retry_loc ─ expand_ctx ─ escalate ─────────┘
                                                                      (or accept / abstain)
```

- `accept`: terminal, `loop_terminated="accepted"`
- `abstain`: replaces answer with "Unanswerable", `loop_terminated="abstained"`
- `retry_localization`: re-runs localize/inspect/expand/answer/verify with `confidence_threshold *= 0.7`
- `expand_context`: re-runs only expand/answer/verify with `adjacency_pad *= 1.5` (capped at 0.30)
- `escalate_reasoner`: re-runs only answer/verify with `escalation_hint=verdict.reason`
- `max_retries=2` default; `=0` disables loop (regression guard)

### TrajectoryStep schema

`src/focusparse/traces/recorder.py` — every retry call records its own TrajectoryStep with `args["retry_attempt"]` for trace attribution. Step indices are unique across the cascade + loop via `_StepCounter`.

### Stage-level metrics flow

```
record (per-example dict)  ─▶  compute_stage_metrics  ─▶  StageMetrics
        + example                 + image_dims_by_page              │
                                                                    ▼
                                                               record["stages"]
                                                                    │
                                                                    ▼
                                                       _aggregate_stages (rehydrate)
                                                                    │
                                                                    ▼
                                                          AggregateStageMetrics
                                                                    │
                                                                    ▼
                                                       run.json::stage_aggregate
                                                                    │
                                                                    ▼
                                                          scripts/diff_runs.py
```

### Cache convention

All tools content-address on `sha256(input_args)` and persist under `<config.cache.root>/<role>/`. Roles: `layout/`, `crops/`, `text_layer/`, `text_index/`. The `_role_cache_dir(name)` helper at `src/focusparse/pipeline/workflow.py:135-142` is the single source.

## Historical Context

- Original master plan: `plans/2026-04-13-focusparse-agentic-pipeline.md` — the 6-phase v1 roadmap (scaffold → workflow → tools → scoring → multi-tier → trajectory export)
- Active plan: `plans/2026-04-27-phase2-sota-leverage.md` — the SOTA-leverage tail with the gate ordering (metrics first)
- Roadmap: `.claude/memory/project_roadmap.md` (also at user-level memory) — full 12-item categorization Phase 2 / Phase 3 / Phase 4+
- Scope decision: `.claude/memory/MEMORY.md:11-27` — narrow to localize/inspect/expand_context; freeze plan/route/answer/verify
- Running changelog: `.claude/memory/MEMORY.md:78-164` — every substantive commit since 2026-04-13

## Test counts at each phase boundary

| Phase                           | Suite size | Delta | Notes                                                        |
| ------------------------------- | ---------- | ----- | ------------------------------------------------------------ |
| Initial scaffold                | ~50        | —     | Phase 1 baseline                                             |
| End of Phase 2 sub-phases 2a-2h | 285        | +235  | All 7 stages real (deterministic)                            |
| Item 1 (page-score fix)         | 287        | +2    | Regression tests                                             |
| Item 2 (stage-level metrics)    | 332        | +45   | 32 stage_metrics + 12 diff_runs + 3 harness wiring           |
| Item 3 (verifier→retry loop)    | 340        | +8    | One per loop path (8 paths)                                  |
| **Current `main`**              | **340**    | —     | All passing (1 skipped streaming, 1 deselected pre-existing) |

## Open Questions

1. **Does the verifier→retry loop help in aggregate?** The n=1 smoke was inconclusive (loop fired, didn't help, +200% cost). 30-example A/B currently running in background (`results/hf/ab-baseline-noloop/` → `results/hf/ab-with-loop/`). Need to diff the two via `scripts/diff_runs.py` to know.

2. **Should `expand_context` tool stub be deleted?** The orphan tool at `src/focusparse/tools/expand_context.py` raises NotImplementedError but the actual graph-aware logic now lives in `src/focusparse/pipeline/expander.py` (called directly by workflow). The tool seam is dead code per the current architecture; safe to delete OR repurpose for item 5's typed graph walker.

3. **Are multi-scale crops a Phase 3 priority or a quick win?** The packet schema fields exist; only the inspector + reasoner prompt need extending. Could be a single-day sub-phase rather than waiting for chart/table specialists.

4. **HTML report template engine choice:** Jinja2 is in dev extras already. Alternative: render to Markdown + commit static HTML. Markdown is more grep-friendly but loses the bbox overlay rendering.

## Related Research

- Plans: `plans/2026-04-13-focusparse-agentic-pipeline.md` (master), `plans/2026-04-22-focusparse-hf-eval.md` (eval Phase A-D), `plans/2026-04-27-phase2-sota-leverage.md` (current)
- Memory: `.claude/memory/MEMORY.md`, `.claude/memory/project_roadmap.md` (in-repo team-facing); user-level mirrors at `~/.claude/projects/-Users-gabrielbo-projects-FocusParse/memory/`
