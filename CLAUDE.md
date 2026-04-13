# CLAUDE.md

Minimalist operational card for Claude Code (and humans) working in this repo.
For **product goals and architecture**, read [`README.md`](README.md) and the active plan in [`plans/`](plans/) first. For **running agent-written context**, read [`.claude/memory/MEMORY.md`](.claude/memory/MEMORY.md).

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

| Role | Tier | Provider:model |
|---|---|---|
| planner | cheap | gemini:gemini-3.1-flash-preview |
| router | cheap | gemini:gemini-3.1-flash-preview |
| localizer rerank | mid | anthropic:claude-haiku-4-5 |
| reasoner | frontier | openai:gpt-5.4 |
| verifier | mid | anthropic:claude-haiku-4-5 |

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

## Repo layout (10-second tour)

- `src/focusparse/pipeline/` — workflow `@step`s, one file per stage, 1:1 with the state machine in the plan.
- `src/focusparse/tools/` — `FunctionTool` primitives. `inspect_region` has three modes: `image` / `element` / `region`. Do not add a fourth without updating the plan.
- `src/focusparse/evidence/packet.py` — **the contract**: every reasoner call sees `EvidencePacket[]`, never raw pages.
- `src/focusparse/eval/scoring.py` — wraps parser-bench's scorer, adds `score_evidence_reward` (lazy-answer penalty).
- `src/focusparse/traces/export.py` — trajectory JSONL schema is **the interface with FocusTrain**. Bump `schema_version` for any field change and note it in `.claude/memory/MEMORY.md`.
- `third_party/parser-bench/` — git submodule, read-only. Do not edit.

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

| Symptom | Likely cause |
|---|---|
| Whole-page crops only in a run | Layout endpoint stub fallback. Check `HF_TOKEN` and endpoint status. |
| `Generated 0 candidate examples` | Dataset loader mismatch (schema drifted in parser-bench submodule); bump submodule SHA. |
| Empty visible response from Gemini | Set `thinking_budget ≥ 1024`; Gemini 2.5/3.x otherwise spends all tokens on hidden reasoning. |
| GPT-5.x "max_tokens not supported" error | Use `max_completion_tokens` (different param name than GPT-4.x). |
| Multi-turn agent reports 0 tokens | Token usage not propagated from `TokenCountingHandler` — integration test catches this. |

## Changelog

Newest first.

- `2026-04-13` — Initial scaffold: plan, `pyproject.toml`, `.claude/` config, `src/focusparse/` stubs, dataset loader, parser-bench submodule seam.

---

When in doubt: **read `README.md` for product, the active plan for design, `.claude/memory/MEMORY.md` for running context.**
