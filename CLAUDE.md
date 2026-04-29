# CLAUDE.md

Lean operational card. **Running context + scope + changelog live in [`.claude/memory/MEMORY.md`](.claude/memory/MEMORY.md)** and the files it indexes — read them on init. Product goals + architecture: [`README.md`](README.md) and the active plan in [`plans/`](plans/).

> **Research framework.** Every change to this repo is judged by whether it moves a cell in the headline 4-method × 2-task × 2-metric table that drives the paper claim. See **[`MEMORY.md` → "Research framework"](.claude/memory/MEMORY.md)** for the table spec, the development priority (FocusParse harness is the product; comparator methods are scaffolding), and the active plan at [`plans/2026-04-29-research-driven-eval-framework.md`](plans/2026-04-29-research-driven-eval-framework.md).

## What this repo does

FocusParse runs a hierarchical, budget-aware agentic workflow over documents from the `gabrielbo/parser-bench` benchmark and emits citation-grounded answers + trajectory traces. Consumes `parser-bench` **read-only** as a git submodule at `third_party/parser-bench/`.

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

## Keeping CLAUDE.md lean

This file is operational (commands / structure / contracts / failure modes). It is **not** the changelog. Running memory — recent substantive changes, scope decisions, training recipe, project facts — lives in `.claude/memory/` and is indexed by `MEMORY.md`. Update there. Only touch CLAUDE.md when an operational fact changes: a new command, env var, endpoint, load-bearing contract, or failure mode.

## Common failure modes

| Symptom                                  | Likely cause                                                                                  |
| ---------------------------------------- | --------------------------------------------------------------------------------------------- |
| Whole-page crops only in a run           | Layout endpoint stub fallback. Check `HF_TOKEN` and endpoint status.                          |
| `Generated 0 candidate examples`         | Dataset loader mismatch (schema drifted in parser-bench submodule); bump submodule SHA.       |
| Empty visible response from Gemini       | Set `thinking_budget ≥ 1024`; Gemini 2.5/3.x otherwise spends all tokens on hidden reasoning. |
| GPT-5.x "max_tokens not supported" error | Use `max_completion_tokens` (different param name than GPT-4.x).                              |
| Multi-turn agent reports 0 tokens        | Token usage not propagated from `TokenCountingHandler` — integration test catches this.       |

## Changelog

Lives in `.claude/memory/project_changelog.md`. Append an entry there after any substantive commit (new pipeline stage, new tool, new env var, new HF endpoint, trajectory schema bump, new failure mode). Skip trivialities. Don't add changelog lines to this file.

---

When in doubt: `README.md` for product, the active plan for design, `.claude/memory/MEMORY.md` for running context.
