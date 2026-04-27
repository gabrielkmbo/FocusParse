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
