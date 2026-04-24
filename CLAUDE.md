# CLAUDE.md

Minimalist operational card for Claude Code (and humans) working in this repo.
For **product goals and architecture**, read [`README.md`](README.md) and the active plan in [`plans/`](plans/) first. For **running agent-written context**, read [`.claude/memory/MEMORY.md`](.claude/memory/MEMORY.md).

## What this repo does

FocusParse runs a hierarchical, budget-aware agentic workflow over documents from the `gabrielbo/parser-bench` benchmark and emits citation-grounded answers + trajectory traces. Consumes `parser-bench` **read-only** as a git submodule at `third_party/parser-bench/`.

## Narrowed scope — what we optimize (2026-04-24)

The 7 pipeline stages are intentionally unequal. Treat them in three tiers:

| Stage              | Status                           | Optimization priority                                                                                     |
| ------------------ | -------------------------------- | --------------------------------------------------------------------------------------------------------- |
| plan               | real cheap-tier LLM              | **frozen**: works; tweak only if a new question_family shows up                                           |
| route_pages        | real FTS5 + BM25                 | frozen: fine once a text source is wired                                                                  |
| **localize**       | real HF RT-DETRv2                | **main focus**: IoU + recall are ceiling-limited by this stage                                            |
| **inspect**        | **still skeleton**               | **main focus**: sub-phase 2g ReActAgent + tools belt is the biggest single unlock                         |
| **expand_context** | **still skeleton** (passthrough) | **main focus**: graph-aware neighbor attachment (legend / caption / header) is the closest lever after 2g |
| answer             | real frontier-tier VLM           | frozen: quality is downstream of what evidence we hand it                                                 |
| verify             | real mid-tier LLM                | frozen: structured output + retry-loop wiring is done                                                     |

**Practical implication**: new work lands on `src/focusparse/pipeline/{localizer,inspector,expander}.py` and `src/focusparse/tools/*` (especially `inspect_region`, `expand_context`). Other pipeline files should only change when touched by cross-cutting refactors (typed events, tier router, trajectory schema). If you find yourself about to "improve" planner/router/reasoner/verifier mid-session, check in first — the answer is almost certainly "not yet."

Long-term goal is still a citation-grounded agentic pipeline trained via trajectory export (see "Training plan" in `.claude/memory/MEMORY.md`), but the _training target_ is also the focus stages — SFT cares about what the inspector chose and what packets the expander built, not about which Gemini version classified the question.

## Daily commands

```bash
uv sync --extra dev
uv run focus status
uv run focus eval --agent simple --backend gemini --model gemini-3.1-pro-preview --split dev --limit 3

uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run pytest
uv run pytest tests/test_scoring.py::test_score_evidence_reward -v
```

Python ≥ 3.11. Ruff line-length 100 (see `pyproject.toml`).

## Environment

Copy `.env.example` → `.env` and fill. Required for most work:

- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` — at least one reasoner provider.
- `HF_TOKEN` — **mandatory** for HF layout endpoint and dataset streaming.

Optional:

- `LLAMA_CLOUD_API_KEY` — LlamaParse/LlamaExtract baseline row (Phase 5).
- `FOCUSPARSE_LAYOUT_ENDPOINT_URL` — override the default parser-bench endpoint.
- `FOCUSPARSE_TIER_*` — override tier assignment per role at runtime.

## Model tiers

Set in [`configs/default.yaml`](configs/default.yaml) under `tiers:` and `roles:`. Change models there, not in code.

Current defaults (tweak as pricing shifts — see `.claude/memory/MEMORY.md` for rationale):

| Role             | Tier     | Provider:model             |
| ---------------- | -------- | -------------------------- |
| planner          | cheap    | gemini:gemini-2.5-flash    |
| router           | cheap    | gemini:gemini-2.5-flash    |
| localizer rerank | mid      | anthropic:claude-haiku-4-5 |
| reasoner         | frontier | openai:gpt-5.4             |
| verifier         | mid      | anthropic:claude-haiku-4-5 |

Escalation is **per-stage** (one tier up on low confidence), never pipeline-wide.

## External endpoints

- **Layout** — `https://jqkx3k3gn4ciymvi.us-east-1.aws.endpoints.huggingface.cloud` (RT-DETRv2 via parser-bench). POST PNG bytes with `Authorization: Bearer $HF_TOKEN`. Rate-limit ≤ 2 req/s; cache on disk in `cache/layout/<doc_sha>.json`. Fall-back stub returns a single full-page bbox — if you see "whole page crops only", the endpoint is down or the token is wrong.
- **HF dataset** — `gabrielbo/parser-bench` (streaming default). Pin via `FOCUSPARSE_DATASET_REVISION` when the benchmark stabilizes.
- **LlamaCloud** (optional) — `llama-cloud` pypi package, used only behind `[llamacloud]` extra.

## NFS (processed documents)

Canonical team path (SSH):

```
llama-nfs:/home/osx-user/shared-experiments/llamacloud-bench-ci/data/parser-bench/
```

Use `focusparse.dataset.nfs.rsync_pull(doc_id)` to hydrate a processed doc locally; `rsync_push` to sync back. Helpers mirror parser-bench's rsync contract (macOS openrsync-safe, `-az` archive+compress, no `--delete`). Requires `llama-nfs` host alias in `~/.ssh/config`.

## Repo layout

```
FocusParse/
├── configs/
│   └── default.yaml              # tiers, roles, budgets, endpoints, dataset, cache, traces
├── plans/                        # authoritative design docs; newest plan is active
├── scripts/                      # one-off entrypoints (reproduce_baselines, compare_tiers, export_traces, fetch_nfs_processed)
├── src/focusparse/
│   ├── cli/                      # `focus` typer app: status | eval | report | export-traces
│   ├── pipeline/                 # workflow @step modules, 1:1 with the state machine
│   │   ├── workflow.py           #   FocusWorkflow + SimpleBaselineAgent
│   │   ├── events.py             #   typed events between steps (no dict payloads)
│   │   └── {planner,router,localizer,inspector,expander,reasoner,verifier}.py
│   ├── tools/                    # FunctionTool primitives (stay small and strong)
│   │   ├── inspect_region.py     #   3 modes: image | element | region (no 4th without plan update)
│   │   ├── run_python.py         #   sandboxed coding-zoom (subprocess + rlimit + import allowlist)
│   │   ├── layout_detect.py      #   HF layout endpoint client; raises on stub responses
│   │   └── {expand_context,get_text_layer,chart_to_table}.py
│   ├── evidence/
│   │   ├── packet.py             #   EvidencePacket — the contract the reasoner sees (never raw pages)
│   │   └── graph.py
│   ├── models/                   # backend clients + tier router
│   │   ├── base.py               #   ModelClient protocol
│   │   ├── tiers.py              #   TierRouter (per-stage escalation, capped per run)
│   │   └── {anthropic,openai,gemini}.py
│   ├── retrieval/                # text_index (sqlite FTS), visual_rerank (deferred, [visual-rerank] extra)
│   ├── dataset/
│   │   ├── loader.py             #   BenchmarkLoader — HF streaming + local JSONL
│   │   └── nfs.py                #   llama-nfs rsync helpers
│   ├── cache/store.py            # content-addressed disk cache (sha256 key over tool args)
│   ├── eval/
│   │   ├── harness.py            #   run_simple_eval / run_focus_eval
│   │   ├── scoring.py            #   score_answer, page_recall, max_iou_over_alternates, score_evidence_reward
│   │   ├── metrics.py            #   aggregate metrics (accuracy, evidence_reward_mean, lazy_answer_rate, usd_per_correct)
│   │   └── report.py             #   HTML report (Phase 4)
│   ├── traces/
│   │   ├── recorder.py           #   TrajectoryRecorder — one RunTrace per example
│   │   └── export.py             #   SFT-ready JSONL; schema_version = "1"
│   ├── utils/config.py           # FocusConfig (YAML + FOCUSPARSE_TIER_* env overrides)
│   └── _parser_bench.py          # file-path shim that loads parser-bench's schema.py without sys.path collision
├── tests/
│   └── fixtures/                 # tiny_datasheet.pdf + golden outputs
├── third_party/parser-bench/     # git submodule, READ-ONLY
├── .claude/
│   ├── settings.json             # permissions, env (FOCUSPARSE_TIER_*), statusLine
│   ├── agents/                   # project subagents: pipeline-engineer, tools-engineer, trace-exporter, eval-runner
│   └── memory/MEMORY.md          # running agent-written context — read this on /init
├── .mcp.json                     # project MCP servers (HF, filesystem)
├── CLAUDE.md                     # this file
├── README.md                     # product overview
└── pyproject.toml                # uv-managed, py ≥ 3.11, ruff line-length 100
```

### Load-bearing contracts (don't break silently)

- `src/focusparse/evidence/packet.py::EvidencePacket` — every reasoner call sees `list[EvidencePacket]`, never raw pages.
- `src/focusparse/eval/scoring.py::score_evidence_reward` — lazy-answer penalty. Zero if no tool calls or no predicted bboxes.
- `src/focusparse/traces/export.py::SCHEMA_VERSION` — interface with the future FocusTrain repo. Bump on any field change and log the migration in `.claude/memory/MEMORY.md`.
- `src/focusparse/tools/inspect_region.py` — exactly 3 modes. A 4th mode needs a plan update first.
- `third_party/parser-bench/` — submodule, read-only. Propose benchmark changes upstream in separate PRs.

### Write-only sinks (gitignored)

- `cache/` — content-addressed crops, OCR, layout responses. Safe to wipe; runs will repopulate.
- `results/` — per-run output JSONs, HTML reports, trajectories.

## What not to do

- **Do not modify `parser-bench`** from this repo. Propose changes upstream in separate PRs.
- **Do not vendor** `liteparse` or `llama_index` source. Import them as libraries.
- **Do not run `run_python`-authored code in-process.** The tool uses a subprocess with `resource.setrlimit` and an import allowlist — threat model is "research-grade sandbox", not "untrusted input". Never deploy FocusParse to accept external questions.
- **Do not silently accept** the layout endpoint's full-page stub. `tools/layout_detect.py` should raise on that shape; callers handle the exception.
- **Do not commit `.env`** — it's gitignored for a reason.

## OSS training (future)

FocusParse v1 **does not train** anything. It emits trajectory JSONL to `results/runs/<ts>/traces.jsonl`. The schema is documented in `src/focusparse/traces/export.py` and fixed at `schema_version = "1"`. Training happens in a future `FocusTrain` repo on Modal, targeting Qwen3-VL-4B with an AgenticOCR-style reward (answer × IoU × coverage − spurious/overlap/lazy penalties). See `.claude/memory/MEMORY.md` § "Training plan" for the living recipe.

## Keeping this file current

After any **substantive** change (new pipeline stage, new tier, new env var, new HF endpoint, trajectory schema bump, new failure mode), append **one line** to `## Changelog` below:

```
YYYY-MM-DD — short imperative summary
```

Skip the changelog line for typos and single-line bugfixes. Agents: when you change something that would mislead the next agent, update both this file and `.claude/memory/MEMORY.md`.

## Common failure modes

| Symptom                                  | Likely cause                                                                                  |
| ---------------------------------------- | --------------------------------------------------------------------------------------------- |
| Whole-page crops only in a run           | Layout endpoint stub fallback. Check `HF_TOKEN` and endpoint status.                          |
| `Generated 0 candidate examples`         | Dataset loader mismatch (schema drifted in parser-bench submodule); bump submodule SHA.       |
| Empty visible response from Gemini       | Set `thinking_budget ≥ 1024`; Gemini 2.5/3.x otherwise spends all tokens on hidden reasoning. |
| GPT-5.x "max_tokens not supported" error | Use `max_completion_tokens` (different param name than GPT-4.x).                              |
| Multi-turn agent reports 0 tokens        | Token usage not propagated from `TokenCountingHandler` — integration test catches this.       |

## Changelog

Newest first.

- `2026-04-24` — Phase 2 sub-phase 2g step 1: replace skeleton inspector with a smart-deterministic tool dispatcher. `inspect_regions` now ranks regions by score, caps at `plan.max_crops` (default 8), and routes each to a tool chain based on region_type. Text-bearing regions (text/table/caption/footnote/list/header/formula + unknown) with a PDF call `get_text_layer(bbox)` for deterministic native text; empty/whitespace-only native text falls back to `inspect_region(mode='element')` Tesseract. Visual regions (picture/chart/figure) get `inspect_region(mode='image')` only — no OCR. Confidence folds OCR confidence into the region score. Fail-safe: every region emits a packet even when all tool calls raise (`provenance.tool="skeleton_inspector_fallback"`). Workflow forwards pdf_path + cache/crops/ + cache/text_layer/ into the inspector; trajectory upgrades `inspect` tier to `deterministic` when a PDF is present and records `n_real_packets` alongside `n_packets`. Tests: `tests/test_inspector.py` (11 tests, all tool-routing paths + fallback + provenance + cache forwarding; monkeypatches the two tools so no PyMuPDF/Tesseract/HF calls). **Step 2 (LLM-driven ReActAgent loop) deferred** — deterministic dispatch is the floor we'll evaluate it against. Full suite: 263 passed. Observation from the re-run smoke: RT-DETRv2 ranks text > picture regions, so score-only top-N can hide the answer region when question_family is figure-heavy — tune ranking next.
- `2026-04-24` — **Narrowed project scope** (CLAUDE.md "Narrowed scope" section): optimization effort is now pinned to three stages — `localize`, `inspect`, `expand_context` — and their tools (`inspect_region`, `expand_context`, `layout_detect`). Other stages (plan / route / answer / verify) are treated as frozen. Also shipped two scoring/harness fixes surfaced by the visual smoke test: (1) `scoring._bbox_iou` now normalizes pixel-space gold against normalized predicted via an optional `image_dims_by_page` map — focus-agent runs finally score IoU correctly (went from `0.0` to `1.0` on the smoke example); (2) `run_focus_eval` + `run_hf_eval.py` + `smoke_visualize.py` gain `pdfs_root` / `--pdfs-root` so the FTS router is actually reachable from the eval harness. 11 new tests total: 4 scoring coord-space + 4 harness pdf_path + 3 workflow path tests. Full suite: 252 passed.
- `2026-04-24` — Phase 3: `inspect_region` tool shipped in all three modes (image/element/region). `image` = PyMuPDF render + PIL crop + content-addressed PNG cache. `element` = image + Tesseract OCR on whole crop (via pytesseract TSV for confidence). `region` = element + `layout_detect` called on the crop (same HF docling layout-v3 endpoint at `jqkx3k3gn4ciymvi...`) for sub-element detection + per-sub-region Tesseract OCR; falls back to element shape when the layout endpoint is unavailable. Input uses `doc_path` (aligns with `get_text_layer`). Tesseract fails soft — missing binary → `ocr_text=None, confidence=0` so `crop_ref` still ships for visual inspection. Tests: `tests/test_inspect_region.py` (20 hermetic tests; mocked `layout_detect` for region mode) + scaffold fix in `tests/test_tools.py`. Also wired parser-bench as a real git submodule pinned to `17927dd` (closes the Codex adversarial-review finding). Full suite: 244 passed.
- `2026-04-24` — Wire `get_text_layer` into `FocusWorkflow`. `FocusWorkflow.run` now accepts an optional `pdf_path: Path | None` kwarg; when supplied and the file exists, the workflow extracts native PDF text per page and feeds it to `route_pages` as `pages_text`, so sub-phase 2f's FTS router is actually exercised end-to-end. Degrades gracefully: missing PDFs → skeleton fallback, out-of-range pages → empty-string entries, race-y disappearance → run keeps going. Trajectory upgrades `route_pages` tier to `text_fts` with `n_text_pages` count when FTS fired. Also made `TextIndex(cache_dir=None)` legal (in-memory sqlite) so tests + ephemeral runs don't pollute CWD with `cache/text_index/`. Two new config hooks (`_text_index_cache_dir`, `_text_layer_cache_dir`) share a common `_role_cache_dir(name)` helper. Added `cache/` to `.gitignore` (was documented as a write-only sink in CLAUDE.md but never listed). Tests: 4 new in `tests/test_workflow.py` covering the FTS path, skeleton fallback, dangling PDF, and out-of-range pages. Full suite: 224 passed.
- `2026-04-24` — Phase 3 start: implement `src/focusparse/tools/get_text_layer.py` on top of PyMuPDF. Reads the native PDF text layer for one page (1-indexed), optionally filtered by normalized bbox (span centroid test), returns joined plain text + absolute-PDF-point span bboxes + page dimensions. Scope excludes OCR fallback — `source="empty_native"` is returned for image-only pages so the caller decides when to escalate. Content-addressed disk cache keyed on `sha256(pdf_bytes + page + bbox)`; cache-hit skips `_extract_page_text` entirely. Missing PDF raises `FileNotFoundError`; out-of-range page raises `ValueError` so plumbing bugs surface immediately. Tests: `tests/test_get_text_layer.py` (9 tests; hermetic — generates PDFs on the fly via PyMuPDF, no binary fixtures). This directly unblocks Phase 2 sub-phase 2f end-to-end — the router's `pages_text` parameter now has a real source. Full suite: 220 passed.
- `2026-04-22` — Phase 2 sub-phase 2f: wire real sqlite FTS5 text retrieval into the router. New `src/focusparse/retrieval/text_index.py::TextIndex` indexes per-doc page text with BM25 ranking (porter stemming, unicode61 tokenization), caches on disk keyed by `sha256(doc_id + page texts)`, and sanitizes user questions so real input like `what's V(CC) maximum?` doesn't crash FTS. `route_pages` now takes `pages_text: dict[int, str] | None` + `text_index_cache_dir`; when text is supplied it returns up to top_k=5 pages ranked by BM25 (`reason_code="text_fts_match"`), backfilled with `text_fts_no_matches` stubs at score 0; when no text is supplied it preserves the pre-2f skeleton shape (every page, score 1.0, `skeleton_all_pages`). Question-family priors are deferred — they need per-page figure/table counts we don't have yet. Tests: `tests/test_text_index.py` (16) + `tests/test_router.py` (14); full suite stays green at 211 passed.
- `2026-04-22` — Phase 2 sub-phase 2e: replace skeleton full-page localizer with a real layout-driven localizer. New `src/focusparse/tools/layout_detect.py` posts PNG bytes to the HF RT-DETRv2 endpoint, retries 502/503/504/429 with exponential backoff, raises `StubResponseError` on the single-full-page stub and `LayoutEndpointUnavailable` on permanent 4xx/timeouts, and caches responses on disk keyed by `sha256(endpoint + png_bytes)`. `propose_regions` now calls `detect_layout` per page, normalizes absolute bboxes to [0,1], blends `page_score * detector_score`, and emits one `RegionCandidate` per detected box; falls back to a full-page skeleton region (per-page, not global) on endpoint failure, missing images, or empty detections, with signal taxonomy `layout_endpoint_down | layout_endpoint_stub | layout_no_boxes_above_threshold | image_missing | no_image_for_page` carried on `supporting_signals` for trace attribution. `FocusWorkflow` threads `images_by_page`, layout endpoint URL, and `<cache_root>/layout` into the localizer. Tests: `tests/test_layout_detect.py` (12 tests, `httpx.MockTransport`, no network) + `tests/test_localizer.py` (10 tests, monkeypatched `detect_layout`).
- `2026-04-22` — Phase 2 sub-phase 2d: replace deterministic skeleton verifier with a mid-tier LLM call that emits `{supported, reason, next_action, confidence}` as strict JSON. `verify_answer` now returns `tuple[VerdictEvent, ModelResponse | None]` so the verify `TrajectoryStep` attributes tokens/cost. `FocusWorkflow` calls `self._client_for("verifier")`; falls back to skeleton-accept when no client is wired. Next_action routing (retry_localization / expand_context / escalate_reasoner) is recorded on the trajectory but not yet looped back into the workflow — that's a later sub-phase. Added `tests/test_verifier.py` (16 tests, submodule-free) + `tests/test_workflow.py::test_focus_workflow_routes_verifier_through_tier_router`.
- `2026-04-22` — Replace stale cheap-tier model name `gemini-3.1-flash-preview` (404s on real API) with `gemini-2.5-flash` (current stable flash). Updates `configs/default.yaml`, `src/focusparse/eval/pricing.py` (pricing $0.30 in / $2.50 out per 1M tokens), `tests/test_pricing.py`, and the CLAUDE.md tier table. Default `uv run focus eval` and `scripts/run_hf_eval.py --agent focus` now route the planner to a real Gemini endpoint without needing `--tier-override planner=mid`.
- `2026-04-22` — Phase 2 sub-phase 2c: replace deterministic planner with a cheap-tier LLM call that classifies `question_family`, `evidence_types`, `budget_class`, `routing_policy` from the question text + domain. `plan_question` now returns `tuple[PlanEvent, ModelResponse | None]` so the plan `TrajectoryStep` attributes tokens/cost. `FocusWorkflow` gains `_client_for(role)` which resolves role-scoped clients via `tier_router`; falls back to deterministic when no router is wired. `run_focus_eval` + `scripts/run_hf_eval.py` thread `tier_router` through. Added `tests/test_planner.py` (15 tests, submodule-free) + workflow integration tests for the tier_router path.
- `2026-04-22` — Fix router/inspector page alignment: `route_pages` now takes `pages: list[int]` instead of positional `n_pages: int` so real page numbers parsed from filenames flow to the inspector; previously the skeleton router emitted pages [1..N] while `_images_by_page` keyed on filename-derived pages, so inspector lookups missed and the reasoner ran blind. Unblocks smoke tests of `--agent focus`.
- `2026-04-22` — Phase D of HF eval plan: wire `run_focus_eval` harness (mirrors `run_simple_eval`'s contract, drives `FocusWorkflow` over all pages) and un-gate `--agent focus` in `scripts/run_hf_eval.py`. Added `scripts/run_hf_eval.py::_protocol_matches_agent` guardrail (simple takes `full_doc|oracle_page|oracle_crop`; focus takes `focus_default`). `scripts/run_hf_matrix.py --phase b` now runnable end-to-end. Tests: `tests/test_focus_harness.py` + CLI validation in `tests/test_hf_eval_cli.py`.
- `2026-04-22` — Phase 2 sub-phases 2a+2b: wire `FocusWorkflow.run` end-to-end with deterministic skeleton planner/router/localizer/inspector/expander/verifier + one real VLM call in the reasoner. Records 7 `TrajectoryStep`s per run, translates packet-id citations back to `{page, bbox}`, drops hallucinated packet refs. Added `tests/test_workflow.py` coverage.
- `2026-04-22` — Add `scripts/run_hf_matrix.py` + `tests/test_hf_matrix_merge.py` (Phase C of HF eval plan): sweep `simple × {full_doc,oracle_page,oracle_crop}` via subprocess to `run_hf_eval.py`, merge per-cell JSONs into `results/hf/matrix_summary.json` preserving existing keys. Phase B (focus agent) still blocked on `FocusWorkflow.run`.
- `2026-04-22` — Add `scripts/run_hf_eval.py` + `src/focusparse/eval/schemas.py` + `tests/test_{eval_schemas,hf_eval_cli}.py` (Phase B of HF eval plan): single-config runner with `--tier-override`, deterministic `tier_sha8` filename, parser-bench-shaped `EvalRunResults` output. No `--backend` flag — reasoner comes from tier config.
- `2026-04-22` — Add `src/focusparse/eval/hf_loader.py` (Phase A of HF eval plan): materialize `gabrielbo/parser-bench` validation split to `<staging>/benchmark.jsonl` + `data/processed/<doc>/images/`, plus `dataset_fingerprint()` for reproducibility.
- `2026-04-22` — Add full repo-layout tree + load-bearing contracts + write-only sinks sections to CLAUDE.md.
- `2026-04-13` — Initial scaffold: plan, `pyproject.toml`, `.claude/` config, `src/focusparse/` stubs, dataset loader, parser-bench submodule seam.

---

When in doubt: **read `README.md` for product, the active plan for design, `.claude/memory/MEMORY.md` for running context.**
