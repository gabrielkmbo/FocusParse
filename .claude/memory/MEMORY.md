# FocusParse — Agent Memory

> Agents: keep this file current. Add a dated entry any time you learn something
> that would not be obvious to the next agent from the code alone — model quirks,
> debugging gotchas, tier-routing decisions, trajectory schema evolutions.
> Structure: one **## YYYY-MM-DD — topic** heading per discovery, newest at top.
> Keep standing context at the top; prune stale entries aggressively.
>
> **This is where running context lives. CLAUDE.md stays lean (commands + structure + contracts).** If you're tempted to put a multi-paragraph note in CLAUDE.md, put it here instead.

## Narrowed scope — what we optimize (2026-04-24)

The 7 pipeline stages are intentionally unequal:

| Stage              | Status                               | Priority                                                       |
| ------------------ | ------------------------------------ | -------------------------------------------------------------- |
| plan               | real cheap-tier LLM                  | **frozen**                                                     |
| route_pages        | real FTS5 + BM25                     | frozen (fine once text source is wired)                        |
| **localize**       | real HF RT-DETRv2                    | **main focus** — IoU + recall are ceiling-limited here         |
| **inspect**        | smart-deterministic (2g step 1)      | **main focus** — step 2 is the LLM-driven ReActAgent loop      |
| **expand_context** | graph-aware neighbor attachment (2h) | **main focus** — tune neighbor taxonomy + adjacency heuristics |
| answer             | real frontier-tier VLM               | frozen (quality is downstream of evidence we hand it)          |
| verify             | real mid-tier LLM                    | frozen (structured output + retry-loop wiring done)            |

Work lands in `src/focusparse/pipeline/{localizer,inspector,expander}.py` and `src/focusparse/tools/*` (especially `inspect_region`, future `expand_context`). Other pipeline files only change for cross-cutting refactors (typed events, tier router, trajectory schema). If you're about to "improve" the frozen stages mid-session, check in first — the answer is almost certainly "not yet."

The SFT training target (future FocusTrain repo) also cares about focus-stage trajectories — what the inspector chose, what packets the expander built — not about which Gemini version classified the question.

## Standing context

- **Benchmark:** `gabrielbo/parser-bench` on HF. Schema: `BenchmarkExample` in the `third_party/parser-bench` submodule.
- **Baseline numbers to beat (parser-bench 2026-04-13 slide deck):**
  - GPT-5.4: full_doc 48.6% → oracle_crop 59.4% (+10.8 pt localization gap)
  - Gemini 3.1 Pro Preview: 42.0 → 50.3 (+8.3 pt)
  - Claude Opus 4.6: 29.8 → 43.2 (+13.4 pt)
- **Cost headroom:** Claude full_doc $0.065/correct vs GPT-5.4 oracle_crop $0.010/correct → ~6× if agentic routing works.
- **Target v1 milestone:** `focus balanced` ≥ +6 pts accuracy at ≤ 0.7× cost-per-correct vs `focus simple gpt-5.4` on dev split.
- **Do not modify `parser-bench`** from this repo — it is a read-only submodule at `third_party/parser-bench/`.

## Environment keys (actually used in .env)

- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (note: not `GOOGLE_API_KEY`), `HF_TOKEN`, `TESSERACT_CMD`, `VLLM_API_KEY`.
- `VLLM_API_KEY` exists for self-hosted vLLM / sglang OSS model serving. Use via `openai` backend + `base_url` when we wire OSS models in Phase 5.

## Training plan (tracked here; not built here)

- Recipe: AgenticOCR-style. SFT on teacher trajectories filtered by dual threshold
  (coverage recall ≥ 0.8 AND IoU ≥ 0.3); then GRPO with reward shape:
  `answer × IoU × coverage − spurious_box − overlap − lazy_full_page`.
- Mask loss so only assistant reasoning + tool-call tokens contribute (AgenticOCR §3.2).
- Base model: Qwen3-VL-4B. Training: **Modal**. Deploy: HF Inference Endpoint.
- Trajectory source: `results/runs/<ts>/traces.jsonl` from FocusParse's `focus eval --tier frontier`
  plus hard negatives where parser-bench teacher and verifier disagreed.
- Training repo (future): `FocusTrain` — consumes traces at `schema_version = "1"`.

## Model quirks (living)

- **Gemini 2.5/3.x**: set `thinking_budget ≥ 1024` or visible response is empty.
- **GPT-5.x**: uses `max_completion_tokens`, not `max_tokens`.
- **Claude Opus 4.6**: full_doc accuracy lags on finance charts; prefer GPT-5.4 as reasoner tier.
- **Gemini 3.1 Pro Preview**: cheapest frontier for `full_doc` per-correct; solid default for early experiments.

## Known sharp edges

- Layout HF endpoint (`jqkx3k3gn4ciymvi…`) returns a **single full-page bbox stub** on failure.
  Signal: "whole page crops only". Check `HF_TOKEN` + backoff logs first; `tools/layout_detect.py` must raise on stub, not succeed silently.
- NFS path uses SSH alias `llama-nfs` — must exist in `~/.ssh/config`. macOS `openrsync` needs `shlex.quote`'d remote paths (lift from parser-bench `scripts/run_generate.py` `_rsync`).
- HF dataset revision is **not** pinned yet (plan §8.4 deferred). Benchmark is still being hardened (contact-sheet bbox fix + 300 dpi oracle crops per parser-bench slide deck 2026-04-13). Re-run baselines whenever the dataset advances; note advances here with the new revision SHA.
- Layout endpoint is **shared** with parser-bench. Rate-limit to ≤ 2 req/s; cache layout output on disk under `cache/layout/<doc_sha>.json` so eval sweeps don't burn shared quota.

## Standing decisions (from plan §8)

- **8.1 parser-bench schema dep**: git submodule at `third_party/parser-bench/`.
- **8.2 visual rerank**: skipped in v1 — FTS-only router. `visual_rerank.py` is a stub seam.
- **8.3 layout endpoint**: cache-on-disk + rate-limited fallback to shared parser-bench endpoint.
- **8.4 HF revision pin**: deferred; `FOCUSPARSE_DATASET_REVISION` env var wired for one-line flip later.

## Changelog

Newest first. Append an entry after any substantive change — new pipeline stage, new tool, new tier, new env var, new HF endpoint, trajectory schema bump, new failure mode. Skip typos and lint-only fixes.

### 2026-04-27 — Phase 2 item 3 default reverted: n=30 A/B says loop hurts

The plan's hard rule (`plans/2026-04-27-phase2-sota-leverage.md:269`) fired: the verifier→retry loop default flipped from `max_retries=2` back to `0` after a real validation A/B showed it hurts more than it helps. Run pair: `results/hf/ab-baseline-noloop/` (n=30, max_retries=0) vs `results/hf/ab-with-loop/` (n=30, max_retries=2), diffed via `scripts/diff_runs.py`. Headline regressions:

```
bbox_iou_mean             0.716 → 0.641   ↓bad
region_recall             0.689 → 0.609   ↓bad
region_precision          0.781 → 0.625   ↓bad
verifier_caught_unsupp.   0.800 → 0.733   ↓bad
loop.retry_helped_rate      —   → 0.091   (only 9% of retries helped)
efficiency.answer.tokens  5979  → 13,300  (+123% cost)
answer_correct            0.0   → 0.0     (both 0% — strict scoring vs VLM prose)
```

Diagnosis: `retry_localization` lowers `confidence_threshold` (× 0.7), surfacing noisier RT-DETRv2 boxes — dilutes top-N signal-to-noise rather than finding better regions. Wrong primitive. Items 4 (query-conditioned reranker) and 5 (evidence-graph expansion) attack the same target more surgically; flip the default back only after one shows a measurable improvement on n≥30.

Also fixed a latent bug surfaced by the default change: the old `while retries_used < self.max_retries` skipped action classification entirely when `max_retries=0`, marking every example "exhausted" even when the initial verdict was "accept". Restructured to `while True` with explicit budget check after accept/abstain branches.

Loop wiring stays in place — all 8 path tests pass, infrastructure correct. Just default-off until proven.

Baseline aggregate (n=30, the new reference for items 4+):

- `page_recall@1=1.000` (router perfect — though staging only stages gold pages, so this is trivial; full-doc staging will stress this)
- `region_recall=0.689`, `region_precision=0.781`, `bbox_iou_mean=0.716` — strong localization
- `lazy_full_page_rate=0.067` — 7% lazy crops
- `verifier_caught_unsupported_rate=0.800` — verifier correctly flags 80% of wrong answers
- `answer_correct=0.000` — VLM prose ("About 50%") doesn't pass strict numeric tolerance against gold ("40%")
- 7 PDFs sourced from `llama-nfs:.../raw/{datasheets,finance}/` via `scripts/source_pdfs_from_nfs.py` (1 finance PDF — `jpm_gtm_us_daily.pdf` — wasn't on NFS; those 2 examples skeleton-fall-back gracefully)

The takeaway for items 4+: the localization stack is healthy and the verifier knows when answers are wrong. The bottleneck is downstream-of-evidence (VLM answer extraction under strict scoring). Item 4's reranker should improve `region_precision` / `lazy_full_page_rate` by pruning the top-N to question-relevant boxes; item 5's evidence graph should improve `cited_evidence_completeness` by attaching the right neighbor types.

### 2026-04-27 — Phase 2 item 3 shipped: verifier→retry control-flow loop

The verifier finally acts as a controller, not just a judge. `FocusWorkflow.run` consumes `verdict.next_action` and re-enters the appropriate stages: `retry_localization` re-runs localize + inspect + expand + answer + verify with a tightened `confidence_threshold` (0.7× per retry); `expand_context` re-runs only expand + answer + verify with a widened `adjacency_pad` (1.5× per retry, capped at 0.30); `escalate_reasoner` re-runs only answer + verify with the verifier's reason as an `escalation_hint` to the reasoner; `abstain` replaces the answer with "Unanswerable" + the verifier's reason as `reasoning_summary`. `accept` is the only happy-path terminator; `max_retries=2` default cap (`max_retries=0` disables the loop, preserving pre-loop behavior).

Refactored: 5 stages (localize/inspect/expand/answer/verify) extracted into private `_run_*` methods so the loop body can call them with the same trajectory-recording semantics. New `_StepCounter` replaces the hardcoded step_index=0..6; every step now has a unique index, including retry steps. Each step records `args["retry_attempt"]` for trace attribution.

Telemetry adds `retries_used`, `loop_terminated ∈ {accepted, abstained, exhausted}`, `loop_retry_helped` (None when retries=0; bool otherwise — True iff initial verdict was unsupported AND final was supported). Reasoner gains optional `escalation_hint` kwarg.

Tests: 8 new in `tests/test_workflow.py` (one per path: accept / retry_loc / expand_ctx / escalate / abstain / exhaustion / max_retries=0 / unknown action) + 2 updates in `tests/test_focus_harness.py` (the `no_loop` sentinel only fires when the verify step is absent — i.e. simple agent — not in the focus workflow). 8 new helpers including `_ScriptedClient` for sequencing verifier responses. Full suite: 332 → 340 passed.

**Real-document A/B vs item-2 baseline (1 example, `dat-Arm_EE382N_4-0001`):**

```
loop.retries_mean              0.0 → 2.0   (loop fired on this example)
loop_terminated_distribution   no_loop=1.0 → exhausted=1.0
loop.retry_helped_rate         —   → 0.0   (didn't fix it)
reasoning.answer_correct       0.0 → 0.0   (still wrong)
efficiency.answer.tokens       4162 → 12500  (+200%)
efficiency.answer.usd          $0.0054 → $0.0163
localization.region_recall     1.0 → 1.0   (unchanged — same regions)
```

The loop wires up cleanly and is observable in telemetry, but on this single example it didn't help — same wrong answer, ~3× cost. Honest gate result: **n=1 isn't enough to draw a conclusion**, so we ship the loop wiring + tests but treat "did it help in aggregate?" as an open question pending a real validation-split sweep. The example happens to hit a known limitation: the VLM can't read the percentage from the diagram crop regardless of how we re-localize/expand. Items 4 and 5 will benefit from this same diff harness; the gate's purpose is to keep us honest, not to gate trivially.

### 2026-04-27 — Phase 2 item 2 shipped: stage-level metrics + diff_runs

Pulled forward from Phase 4 per the user directive — items 3-5 don't ship without measurable A/B deltas, so metrics are the gate. New `src/focusparse/eval/stage_metrics.py` with pure-function `compute_stage_metrics(record, example, image_dims_by_page) -> StageMetrics` covering: routing (page_recall@{1,3,5}, page_precision@5, pages_inspected), localization (region_recall ≥50% coverage, region_precision, bbox_iou_max, lazy_full_page_rate >60%, duplicate_crop_rate IoU>0.7), evidence (cited_evidence_completeness + expansion_useful_rate left None — richer schema lands with item 5), reasoning (answer_correct, is_abstention keyword detect, is_correct_abstention, verifier_caught_unsupported), loop (loop_retries / loop_terminated / loop_retry_helped — defaults to "no_loop" baseline pre-item-3), per-stage efficiency (tokens / usd / latency / tool_calls, summed across multi-step instances).

`aggregate_stage_metrics(list[StageMetrics]) -> AggregateStageMetrics` does mean-of-floats, rate-of-bools, sum-mean-of-efficiency, distribution-of-loop-terminated. None values excluded from means.

Harness wiring: `_score_and_record` flattens `result.trace.steps` to a plain dict, copies telemetry, and stuffs `compute_stage_metrics(...)` into `record["stages"]`. New `_aggregate_stages` rehydrates per-example blocks and writes `stage_aggregate` to `run.json` + the harness return dict. Legacy cached predictions (no `stages` field) fall through to default StageMetrics so resume runs don't crash.

`scripts/diff_runs.py` A/B harness: reads two run.json files (or wrappers), prints stage-by-stage deltas with direction labels (↑good / ↓bad / ↑bad / ↓good for lower-is-better metrics, tradeoff for efficiency / retries). `--format json` for CI piping; legacy fallback when `stage_aggregate` missing. Reference baseline captured at `results/hf/baseline-after-item2/focusparse_focus_focus_default_7d4b816d/run.json` (1 example, `dat-Arm_EE382N_4-0001`, with PDF). Item 3 diffs against this.

Tests: 32 new in `tests/test_stage_metrics.py` (every metric + aggregate), 12 in `tests/test_diff_runs.py` (helpers + CLI subprocess), 3 in `tests/test_focus_harness.py` (per-example stages + run.json stage_aggregate + legacy resume). Suite: 285 → 332 passed.

Real-baseline observation: `region_recall=1.0`, `region_precision=1.0`, `lazy_full_page_rate=0.0`, `verifier_caught_unsupported_rate=1.0`, `bbox_iou_mean=0.443` (cited region wider than gold), `answer_correct=0.0` (VLM still misreads the percentage). Localization ceiling for this example is hit; downstream items 3-5 will have to prove they help on accuracy / tokens / loop-termination distribution rather than localization (which is already maxed for this example).

### 2026-04-27 — Phase 2 item 1 shipped: decoupled localizer scoring

`localizer.py:172` no longer multiplies `pc.score * det.score`. The router answers "which pages?" and the localizer answers "which boxes?"; mixing them via multiplication zeroed every region whenever sqlite FTS5 BM25 returned 0.0 (the single-doc-match degenerate case the smoke surfaced). `region.score = float(det.score)` directly. Page-routing signal (`page_routing=<reason_code>`) added to `supporting_signals` so traces still attribute regions to their routing source; same stamp on the skeleton fallback path. Verified on the smoke: 14 regions on page 50 now score 0.538-0.969 (was all 0.000), the inspector evidence-type boost can finally do its job. Tests: 2 new regression tests in `tests/test_localizer.py`. Suite 285. Item 2 (stage-level metrics + diff_runs.py harness) is the gate for items 3-5 per `plans/2026-04-27-phase2-sota-leverage.md`.

### 2026-04-27 — Phase 2 SOTA-leverage plan + page-score bug surfaced

Real-document smoke (loaded `dat-Arm_EE382N_4-0001` from HF parser-bench, pulled the source PDF from `llama-nfs:.../raw/datasheets/`) confirmed all 7 stages fire end-to-end with real LLM/HF/tool calls. Surfaced a real bug: when sqlite FTS5's BM25 returns 0.0 for a single-document index match, `pc.score=0.0` propagates through `localizer.py` (`region.score = pc.score * det.score`) zeroing every region's rank, killing the inspector's evidence-type boost.

User shared a 12-item SOTA-leverage list (DocLens / AgenticOCR / FinRAGBench-V inspired). Categorized in `plans/2026-04-27-phase2-sota-leverage.md` + `.claude/memory/project_roadmap.md` (mirror at user-level). Phase 2 tail = (1) page-score fix → (2) **stage-level metrics + diff_runs harness — pulled forward from Phase 4 per user directive** → (3) verifier→retry loop → (4) region reranker → (5) evidence-graph expansion. Items 3-5 don't ship without a positive delta on the metric they were supposed to improve. Phase 3 (multi-scale packets, run_python workbench, chart/table specialists) and Phase 4+ (page navigator visual recall, answer sampling, unanswerable protocol, learned policy, hard-negative mining) remain in the roadmap.

### 2026-04-24 — sub-phase 2h: graph-aware expand_context

Replaced the passthrough expander with real neighbor attachment. For each packet, finds annotation-type regions (caption/footnote/section_header/title/page-header/page-footer) on the same page that overlap a padded bbox (8% default pad), ranks by vertical distance to packet center + score, caps at 4 per packet. Crops each via `inspect_region(mode='image')` and stamps `linked_crop_refs` / `linked_neighbor_types` on the packet. `expand_context:nN` tag appended to `provenance.args_hash`. Passthrough when `regions` or `pdf_path` is None — legacy one-arg shape still works. Tests: `tests/test_expander.py` (14). Suite 283. All three focus-stage skeletons (localize / inspect / expand_context) are now real.

### 2026-04-24 — inspector evidence-type-aware ranking

Fixed the smoke-test observation. `_expand_evidence_types()` maps planner-vocab ("figure", "table", "chart", "text", ...) to detector labels (picture/image/chart/section_header/...) via `_EVIDENCE_TYPE_ALIASES`; `_rank_score()` applies 1.5x boost to regions whose type matches `plan.evidence_types`. Confident picture (0.7) now beats confident text (0.92). Packet.confidence still carries raw score — boost is ranking-only. Smoke confirms: VLM now cites a picture region in the diagram area instead of a Section-header. Tests: 6 new in `tests/test_inspector.py` (17 total). Suite 269.

### 2026-04-24 — sub-phase 2g step 1: smart-deterministic inspector

Replaced the skeleton inspector with a tool dispatcher. Per region: crop via `inspect_region(mode='image')`, then text-bearing regions with a PDF call `get_text_layer(bbox)` (native), falling back to `inspect_region(mode='element')` Tesseract on empty native text; visual regions (picture/chart) get crop only. Ranked by score, capped at `plan.max_crops`. Workflow forwards `pdf_path` + `cache/crops/` + `cache/text_layer/`. Tier upgrades to `deterministic` when PDF present. Tests: `tests/test_inspector.py` (11). **Step 2 (LLM-driven ReActAgent loop) deferred.** Full suite 263. Smoke observation: RT-DETRv2 ranks text > picture regions, so top-N by raw score can hide answer regions for figure-heavy questions — tune ranking next.

### 2026-04-24 — narrowed scope + scoring/harness fixes

Pinned optimization to `localize` / `inspect` / `expand_context` (see scope table above). Fixed two bugs surfaced by the visual smoke: (1) `scoring._bbox_iou` now normalizes pixel-space gold against normalized predicted via `image_dims_by_page`; focus-agent IoU went from 0.0 to 1.0 on the smoke example. (2) `run_focus_eval` + `run_hf_eval.py` + `smoke_visualize.py` gain `pdfs_root`/`--pdfs-root` so the FTS router is reachable from the eval harness. 11 new tests; suite 252.

### 2026-04-24 — Phase 3: `inspect_region` tool (3 modes)

`image` = PyMuPDF render + PIL crop + content-addressed PNG cache. `element` = image + Tesseract OCR via pytesseract TSV for confidence. `region` = element + `layout_detect` on the crop for sub-element detection + per-sub-region OCR; falls back to element shape when the layout endpoint is unavailable. Input uses `doc_path`. Tesseract fails soft. Tests: `tests/test_inspect_region.py` (20). Also wired parser-bench as a real git submodule pinned to `17927dd` (closes Codex adversarial-review finding). Suite 244.

### 2026-04-24 — `get_text_layer` wired into workflow + sub-phase 2f E2E

`FocusWorkflow.run(pdf_path=...)` extracts native text per page and feeds `pages_text` to the router. Graceful degradation: missing PDFs → skeleton, out-of-range pages → empty entries. Trajectory upgrades `route_pages` tier to `text_fts` with `n_text_pages` count. `TextIndex(cache_dir=None)` legal (in-memory sqlite). `_role_cache_dir(name)` shared helper for cache dirs. `cache/` added to `.gitignore`. Suite 224.

### 2026-04-22 through 2026-04-24 — Phase 2 sub-phases + Phase 3 start

2a+2b: workflow wiring (skeleton stages + real VLM reasoner). 2c: cheap-tier LLM planner. 2d: mid-tier LLM verifier with `{supported, reason, next_action, confidence}` JSON. 2e: layout-driven localizer via HF RT-DETRv2 endpoint + stub detection + disk cache. 2f: sqlite FTS5 `TextIndex` with BM25, porter stemming, query sanitization. `get_text_layer` tool on PyMuPDF. Replaced stale `gemini-3.1-flash-preview` with `gemini-2.5-flash`. Router/inspector page alignment fix (`route_pages` takes `pages: list[int]`).

### 2026-04-22 — HF eval infrastructure (Phases A-D)

`hf_loader.py` materializes `gabrielbo/parser-bench` validation split (stress rows filtered) to staging; `dataset_fingerprint()` for reproducibility. `scripts/run_hf_eval.py` single-config runner with `--tier-override` + deterministic `tier_sha8` filename; no `--backend` flag (reasoner from tier config). `scripts/run_hf_matrix.py` sweeps `simple × {full_doc,oracle_page,oracle_crop}` via subprocess, merges per-cell JSONs. `run_focus_eval` harness mirrors `run_simple_eval`. `_protocol_matches_agent` guardrail.

### 2026-04-13 — Initial scaffold

Plan written, repo scaffolded, parser-bench submodule seam created.
