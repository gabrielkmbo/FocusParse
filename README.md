# FocusParse

Agentic, budget-aware evidence-localization pipeline for **high-resolution financial charts and technical datasheets**. Consumes the [`gabrielbo/parser-bench`](https://huggingface.co/datasets/gabrielbo/parser-bench) benchmark; produces citation-grounded answers, trajectory traces, and cost/latency telemetry.

Built on [`run-llama/workflows-py`](https://github.com/run-llama/workflows-py) + [`run-llama/llama_index`](https://github.com/run-llama/llama_index) `ReActAgent`.

## North star

> Match frontier-VLM quality on medium/hard localized-evidence QA at a fraction of the cost, and emit trajectories suitable for later OSS distillation (Qwen3-VL) in a separate `FocusTrain` repo.

See [`plans/2026-04-13-focusparse-agentic-pipeline.md`](plans/2026-04-13-focusparse-agentic-pipeline.md) for the authoritative design.

## Pipeline

```
PLAN → ROUTE_PAGES → PROPOSE_REGIONS → INSPECT → EXPAND_CONTEXT → ANSWER → VERIFY
 cheap     cheap        deterministic   mid/front    det+LLM       frontier    mid
```

Per-stage model tier routing; escalation is per-stage, never pipeline-wide. Full architecture diagram in the plan §3.1.

## Quickstart

```bash
# 1. Clone + init parser-bench as a submodule (schema source)
git clone <this-repo> FocusParse && cd FocusParse
git submodule add https://github.com/gabrielkmbo/parse-bench third_party/parser-bench
git submodule update --init --recursive

# 2. Install (uv-managed, Python ≥ 3.11)
uv sync --extra dev

# 3. Secrets
cp .env.example .env
# Fill in: OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, HF_TOKEN

# 4. Smoke test — reproduce parser-bench's single-shot baseline
uv run focus status                                         # print tier + env
uv run focus eval --agent simple \
  --backend gemini --model gemini-3.1-pro-preview \
  --split dev --limit 3

# 5. Run the lens workflow (after Phase 2)
uv run focus eval --agent focus --tier balanced \
  --budget tokens=120k,tool_calls=12,crops=8 \
  --split dev --limit 200 \
  --export-traces results/runs/$(date +%Y%m%d_%H%M%S)/traces.jsonl
```

## Repo layout

| Path | Role |
|---|---|
| `src/focusparse/pipeline/` | Workflow `@step`s — planner, router, localizer, inspector, expander, reasoner, verifier. |
| `src/focusparse/tools/` | `FunctionTool`-wrapped primitives. `inspect_region` (3 modes), `run_python` (sandboxed coding-zoom), `get_text_layer`, `expand_context`, `chart_to_table`, `layout_detect`. |
| `src/focusparse/evidence/` | `EvidencePacket` contract + lightweight evidence graph. |
| `src/focusparse/models/` | Backend clients + tier routing. |
| `src/focusparse/retrieval/` | FTS index for page routing. |
| `src/focusparse/cache/` | Content-addressed crop/OCR/layout cache. |
| `src/focusparse/dataset/` | HF dataset loader (streaming default) + NFS helpers. |
| `src/focusparse/eval/` | Harness, scoring (wraps parser-bench), HTML report. |
| `src/focusparse/traces/` | Trajectory recorder + SFT-ready JSONL export. |
| `src/focusparse/cli/` | `focus` CLI. |
| `configs/` | Model tiers, budgets, endpoints. |
| `plans/` | Implementation plans — authoritative design docs. |
| `third_party/parser-bench/` | Benchmark submodule (read-only). |
| `.claude/` | Claude Code harness config (settings, project subagents, running memory). |

## Non-goals

- **Not** a benchmark generator (that's `parser-bench`).
- **Not** a training codebase (that's a future `FocusTrain` repo; FocusParse only emits trajectory JSONL).
- **Not** a fork of `liteparse` or `llama_index` (consumed as deps, never modified).
- **Not** a general-purpose parser — optimized for finance charts + datasheets with citation-required QA.

## License

Apache-2.0.
