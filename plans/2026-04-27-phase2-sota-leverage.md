# Phase 2 SOTA-leverage tail — measurement first, then loop + rerank + graph

Date: 2026-04-27
Active until: items 1-5 land + the smoke shows the loop firing with measurable per-stage deltas
Scope: tail of Phase 2 (Lens workflow v1) — stays inside the narrowed scope (`localize` / `inspect` / `expand_context`) plus workflow control flow that drives them.

## Context

The user shared a 12-item SOTA-leverage list (DocLens-style page navigator + answer sampling, AgenticOCR-style trace-trained policy + reward shape, FinRAGBench-V-style chart/table specialists). Full categorization in `.claude/memory/project_roadmap.md`.

This plan covers the five highest-leverage Phase 2 items:

1. Page-score zeroing fix (smoke-test bug)
2. **Stage-level eval metrics — pulled forward** (was Phase 4 in the original list). Without these we can't tell whether the verifier loop, reranker, or graph expansion actually improved localization vs. just adding complexity. Lands BEFORE the larger items so each one ships with a measurable delta.
3. Verifier→retry control flow
4. Query-conditioned region reranker
5. Evidence-graph expansion

Phase 3 and Phase 4+ items remain in the roadmap.

---

## 1. Page-score zeroing fix

**Symptom (from 2026-04-27 real-document smoke):** When `route_pages` returns a single page with `reason_code="text_fts_match"`, sqlite FTS5's BM25 against a single-document index returns 0.0. The localizer then computes `region.score = pc.score * det.score = 0 * det.score = 0` for every region. The inspector's evidence-type ranking boost (`score * 1.5`) becomes `0 * 1.5 = 0`. Sort order collapses to enumeration order.

**Fix (Option B from earlier discussion — "decouple ranking"):**

- Localizer: rank regions by `det.score` directly. Drop the `pc.score * det.score` multiplication.
- `pc.score` becomes a routing signal only: "this page was selected" (binary).
- Add `page_routing_score` to `RegionCandidate.supporting_signals` for trace attribution.

**Files:**

- `src/focusparse/pipeline/localizer.py:172` — change `score = pc.score * det.score` to `score = det.score` and add the routing signal
- `tests/test_localizer.py` — update score-blend test + add test asserting page_score=0 doesn't zero region scores
- `tests/test_inspector.py` — update the existing "ranks by score desc" test if it depends on the multiplication

**Verification:**

- Re-run `scripts/smoke_visualize.py --pdfs-root ~/.cache/focusparse/pdfs`
- Confirm region scores are non-zero in trajectory.json
- Confirm picture regions surface above text regions when `evidence_types=[figure]`

---

## 2. Stage-level eval metrics (PULLED FORWARD from Phase 4)

**Why pulled forward:** Without per-stage metrics we ship items 3-5 blind — we can't tell whether the verifier loop / reranker / graph actually improved localization or just added complexity, latency, and cost. AgenticOCR's reward design explicitly separates coverage, localization precision, spurious boxes, redundant overlap, and lazy full-page parsing for exactly this reason. Lands BEFORE the bigger items so each one ships with a measurable delta against a baseline.

**Metrics to compute per example, aggregated per run:**

Page routing (`route_pages` stage):

- `page_recall@k` — fraction of examples where at least one gold supporting page appears in top-k routed candidates (k=1, 3, 5)
- `page_precision@k` — fraction of routed candidates that are gold supporting pages
- `pages_inspected_count` — how many pages the inspector actually visited

Region localization (`localize` + `rerank` stages):

- `region_recall` — does any predicted bbox cover ≥ 50% of any gold bbox? (uses existing `image_dims_by_page` normalization)
- `region_precision` — fraction of predicted bboxes that intersect a gold bbox
- `bbox_iou_max` — already computed; alias for clarity
- `lazy_full_page_rate` — fraction of cited bboxes covering > 60% of page area
- `duplicate_crop_rate` — fraction of citations whose IoU with another citation > 0.7
- `region_minimality` — mean (1 − cited_area_fraction) over correctly-localized examples

Evidence sufficiency (`inspect` + `expand_context` stages):

- `cited_evidence_completeness` — does the cited packet's text/OCR contain a token from the gold answer? (proxy for "evidence supports answer")
- `expansion_useful_rate` — fraction of expansions where the answer cites the linked neighbor (requires citation-tracking)

Reasoning (`answer` + `verify` stages):

- already-tracked: `answer_correct`, `evidence_reward`, `is_lazy`
- new: `abstention_precision`, `abstention_recall` — for examples where verifier emitted `abstain`, is the prediction "Unanswerable"?
- new: `verifier_caught_unsupported` — fraction of wrong answers where `verdict.supported=false`

Loop behavior (after item 3 lands):

- `loop_retries_mean` — mean number of retries per example
- `loop_retry_helped_rate` — fraction of retries where the answer changed AND scored higher
- `loop_terminated` distribution — accepted / abstained / exhausted

Efficiency (already tracked, surface per stage):

- `tokens_in/out_per_stage`, `usd_per_stage`, `tool_calls_per_stage`, `latency_ms_per_stage`

**Design:**

- New module `src/focusparse/eval/stage_metrics.py` with `compute_stage_metrics(per_example, examples) -> StageMetricsBundle`. Pure function over the per-example records the harness already writes.
- `_score_and_record` (in `harness.py`) emits a `stages` dict alongside the existing top-level fields:

  ```json
  {
    "example_id": "...",
    "answer_correct": 1.0,
    "stages": {
      "route_pages": { "recall@1": 1.0, "pages_inspected": 1 },
      "localize": {
        "region_recall": 1.0,
        "lazy_full_page": 0,
        "duplicates": 0
      },
      "inspect": { "cited_completeness": 1.0, "n_real_packets": 8 },
      "expand": { "n_neighbors_attached": 4, "useful_neighbors": 1 },
      "verify": { "caught_unsupported": false }
    }
  }
  ```

- `aggregate()` (in `eval/metrics.py`) gains a `stages` block in the aggregate that computes mean/median/distribution per metric.
- `run.json` manifest gets a top-level `stage_metrics` block summarizing all stages.
- New CLI: `uv run python scripts/diff_runs.py runA runB` — prints stage-by-stage delta tables so we can A/B item 3 vs the baseline. Output:

  ```
  Stage             Metric                runA      runB      Δ
  ------------------------------------------------------------------
  localize          region_recall         0.62      0.71      +0.09
  inspect           cited_completeness    0.55      0.70      +0.15
  ```

**Files:**

- `src/focusparse/eval/stage_metrics.py` (new) — `StageMetricsBundle`, `compute_stage_metrics`, `aggregate_stage_metrics`
- `src/focusparse/eval/metrics.py` — add `stages` block to `AggregateMetrics`
- `src/focusparse/eval/harness.py` — wire `compute_stage_metrics` into `_score_and_record`; persist in `per_example.jsonl`
- `scripts/diff_runs.py` (new) — A/B helper for CLI deltas
- `tests/test_stage_metrics.py` (new) — pure-function tests covering each metric (lazy_full_page, duplicate, page_recall, completeness)
- `tests/test_focus_harness.py` — assert `stages` block appears in run.json + per_example records

**Verification:**

- Smoke writes `stages` block; values look sensible for the existing example
- Diff against the previous baseline run shows zero deltas (no behavior change yet)
- The diff harness will give items 3-5 their measurable signal

**This is the gate for the rest of the plan.** Don't ship items 3, 4, or 5 without first running the diff harness against a stable baseline.

---

## 3. Verifier→retry control flow

**Why:** This is the highest-leverage architectural change in the user's list. The verifier already emits `next_action ∈ {accept, retry_localization, expand_context, abstain, escalate_reasoner}` but `FocusWorkflow.run` never consumes it. Without loops we're not actually agentic.

**Design:**

- `FocusWorkflow.run` gains a retry budget (default `max_retries=2`).
- After `verify`, if `verdict.next_action != "accept"` and `retries_used < max_retries`:
  - `retry_localization`: re-run `propose_regions` with a wider confidence threshold or a "last attempt failed" signal
  - `expand_context`: re-run `expand_context` with `adjacency_pad *= 1.5` to widen the neighbor net
  - `escalate_reasoner`: re-run `answer` with the same packets but a stricter prompt ("the previous answer was unsupported")
  - `abstain`: terminate with `answer="Unanswerable"` and an `abstain_reason` from the verifier
- Each retry records its own `TrajectoryStep` so traces show the loop.
- `accept` is the only happy-path terminator.

**Schema/contract changes:**

- `TrajectoryStep` already supports recording multiple steps per stage — no schema change needed
- Add `retries_used: int` to `WorkflowResult.telemetry`
- Add `loop_terminated: Literal["accepted", "abstained", "exhausted"]` to telemetry for trace export

**Files:**

- `src/focusparse/pipeline/workflow.py` — add the loop, the retry budget, the per-action dispatch
- `tests/test_workflow.py` — new tests: each next_action triggers correct re-execution; retry budget exhausted → abstain; verifier accept → no retry
- `src/focusparse/traces/recorder.py` — confirm multi-step-per-stage works (probably already does)

**Verification:**

- Smoke shows ≥ 1 retry path firing on the existing example (verifier already says `next_action=expand_context` consistently)
- Per-example record carries `retries_used` and `loop_terminated`

---

## 4. Query-conditioned region reranker

**Why:** The localizer returns 14 layout boxes for our smoke page, but only 2-3 are actually relevant to the question. The inspector takes top-N by detector score, which biases toward text. Evidence-type boost helped, but a query-aware rerank is the right primitive.

**Design:**

- New stage `rerank_regions` between `propose_regions` and `inspect_regions`.
- Uses the `localizer_rerank` tier (already configured at `mid` in `configs/default.yaml`).
- Input: `QuestionEvent`, `PlanEvent`, `RegionsEvent` + page thumbnails.
- LLM call returns per-region `{relevance: float, needed_for: str, missing_context: list[str], inspect_mode: str}`.
- Output: `RegionsEvent` with regions ranked by `relevance * det.score`, and `region.expansion_hints` populated from `missing_context`.

**Skip path:** when `tier_router` is None or no client is wired, the rerank is a no-op (keeps existing tests green).

**Files:**

- `src/focusparse/pipeline/region_reranker.py` (new) — the rerank function + structured prompt
- `src/focusparse/pipeline/events.py` — extend `RegionCandidate` with optional `relevance: float` and `needed_for: str | None`
- `src/focusparse/pipeline/workflow.py` — insert the rerank call after localize, record a TrajectoryStep
- `tests/test_region_reranker.py` (new) — mock the LLM; cover JSON parse, fallback when LLM fails, tier_router=None passthrough
- `tests/test_workflow.py` — new test wiring rerank through the pipeline

**Verification:**

- Smoke shows a rerank step in trajectory.json with per-region relevance scores
- Picture regions outrank text regions when the question is figure-heavy
- The `needed_for` field flows into `expansion_hints` so the expander knows which neighbor types to prefer

---

## 5. Evidence-graph expansion

**Why:** Current `expand_context` does spatial-only neighbor attachment (8% bbox pad → any annotation-type region overlapping). That's a heuristic. A typed graph encodes domain knowledge:

- charts: `chart_plot_area → {legend, x_axis, y_axis, footnote, caption, title}`
- tables: `table_row → {column_header, condition_note, unit_row}`
- spec values: `spec_value → {unit_note, package_constraint, temperature_constraint}`
- figures: `figure → {caption, footnote}`
- pages: `figure → {continuation_on_next_page}` (cross-page edges)

**Design:**

- Define `EVIDENCE_GRAPH: dict[str, list[NeighborSpec]]` keyed on the primary region's `region_type` (or `region_type + figure_class` for charts).
- Each `NeighborSpec` is `(target_region_type, spatial_constraint, required_or_optional)`.
- For each packet, walk the graph to enumerate required neighbor types; find the spatially-best candidate of each type in the localizer's region list.
- Spatial constraints encode domain knowledge: legend is to the right of plot for finance charts; caption is below for figures; footnote is at page bottom; unit-note is in the same row for tables.
- Cap at 4 neighbors per packet (existing).
- When `region.expansion_hints` is set (from the reranker, item 3), bias toward those types.

**parser-bench's gold `evidence_relations`:** these are TRAINING data, not inference data. We don't see them at inference. But they're useful for:

- Validating the graph heuristic in tests
- Eventually training a learned expansion policy

**Files:**

- `src/focusparse/pipeline/evidence_graph.py` (new) — the typed graph definition + neighbor walker
- `src/focusparse/pipeline/expander.py` — replace the current "annotation type + bbox overlap" picker with the graph walker; keep the spatial heuristic as fallback when the graph has no entry for a region_type
- `tests/test_evidence_graph.py` (new) — graph walker semantics, spatial constraints, optional vs required
- `tests/test_expander.py` — extend to cover graph-driven expansion + assert legend attaches for charts even when below the figure (current bbox-pad heuristic might miss this)

**Verification:**

- Smoke shows packets with chart `region_type` getting `legend` neighbors even when the legend is across the page
- `linked_neighbor_types` carries graph-edge labels (e.g., "axis_y", "legend_right") rather than raw region types

---

## Out of scope for this plan (tracked in `project_roadmap.md`)

- **Phase 3:** multi-scale crop packets (#5), `run_python` image workbench (#6), chart/table specialists (#7)
- **Phase 4+ — needs scope-shift conversation:**
  - Stage-level eval metrics (#10) — could pull forward as a Phase 2 stretch
  - Page Navigator with visual recall (#2) — reopens frozen `route_pages`
  - Answer sampler + adjudicator (#8) — reopens frozen `answer`
  - Unanswerable protocol (#9) — reopens frozen `verify`
  - Learned tool policy (#11) — FocusTrain repo
  - Hard-negative mining (#12) — FocusTrain repo

## Execution order

1. Page-score fix (~3 commits, ~½ day)
2. **Stage-level metrics** (~5-6 commits, ~1-2 days) — gate for everything below; baseline run captured before item 3 ships
3. Verifier→retry loop (~5-6 commits, ~2-3 days) — biggest behavior change; diff harness must show `region_recall` / `cited_completeness` / `loop_retry_helped_rate` deltas vs baseline
4. Region reranker (~4-5 commits, ~2 days) — diff must show `region_precision` / `region_recall` / `lazy_full_page_rate` deltas
5. Evidence-graph expansion (~4-5 commits, ~2-3 days) — diff must show `expansion_useful_rate` / `cited_completeness` deltas

Each item lands as multiple focused commits per the granular-commits preference. Each item (3-5) ends with:

1. Re-run `scripts/smoke_visualize.py --pdfs-root ~/.cache/focusparse/pdfs` to confirm trajectory shape
2. Run `scripts/run_hf_eval.py --agent focus --limit N` against a small slice
3. Run `scripts/diff_runs.py <baseline> <new>` and paste the per-stage delta table into the changelog entry

If a delta is negative or zero on the metric the change was supposed to improve, **revert and rethink** rather than shipping more complexity on top.
