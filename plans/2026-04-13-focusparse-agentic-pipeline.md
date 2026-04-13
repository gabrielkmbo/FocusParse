# FocusParse — Agentic High-Resolution Document Parsing Pipeline

> **North star:** a query-conditioned, budget-aware evidence localization system that matches frontier-VLM quality on medium/hard financial-chart and technical-datasheet QA at a fraction of the cost, with fully logged trajectories suitable for later OSS distillation into Qwen3-VL.

**Author:** Gabriel Bo · **Date:** 2026-04-13 · **Plan format:** `/create_plan`

---

## 0. Overview

FocusParse is a **new, standalone repo** that consumes the [`gabrielbo/parser-bench`](https://huggingface.co/datasets/gabrielbo/parser-bench) benchmark and wraps cloud + OSS VLMs in a **hierarchical state-machine workflow** (`PLAN → ROUTE_PAGES → PROPOSE_REGIONS → INSPECT → EXPAND_CONTEXT → ANSWER → VERIFY`) that emits **citation-grounded answers with full cost/tool-use telemetry and exportable trajectories**.

It treats `parser-bench` strictly as a **read-only benchmark**. Any benchmark improvements are proposed via separate PRs to `parser-bench`, never from this repo. This keeps the research harness independent of benchmark curation.

### What FocusParse is

- An **orchestrator** built on `llama-index-workflows` (run-llama/workflows-py) with a `ReActAgent` inner loop for multi-turn tool use.
- A **minimal strong tool layer**: one unified `inspect_region` tool with three semantic modes (image / element / region), plus `expand_context`, `get_text_layer`, `chart_to_table`, `run_python` (for coding-driven high-resolution zoom — this is the Google Agentic Vision idea, not optional).
- An **evidence-packet contract** that always ships page thumbnail + local crop + linked neighbors + OCR snippet + provenance to the reasoner, so localization never strips required context.
- A **multi-tier model router** that starts with a cheap model and escalates per-stage (not per-pipeline) when confidence is diffuse.
- A **trajectory recorder** that saves every (question, plan, tool call, observation, reward-weighted box) tuple to JSONL for later SFT/GRPO on Qwen3-VL (training lives in a future `FocusTrain` repo, not here).

### What FocusParse is **not** (explicit non-goals, to prevent scope creep)

- **Not** a benchmark generator. `parser-bench` owns that.
- **Not** a training codebase. Trajectory export only. Training repo is separate.
- **Not** a fork of `run-llama/liteparse` or `run-llama/llama_index`. We consume them as libraries/CLIs; we do not modify vendor source.
- **Not** a general document parser. We optimize only for finance charts + technical datasheets with **citation-required** QA.
- **Not** a swarm of chatting agents. One orchestrator, specialized `@step`s, deterministic tool execution.

---

## 1. Current state analysis

### What already exists (parser-bench — read-only for us)

- [`src/utils/schema.py`](https://github.com/gabrielkmbo/parse-bench/blob/main/src/utils/schema.py) — `BenchmarkExample` with `supporting_pages`, `supporting_bboxes`, `alternate_bboxes`, `evidence_relations`, `DifficultyScores`, `StressType`, `original_bboxes` (for stress variants). Pin to HF revision once stable (deferred per your answer #9).
- [`src/eval/runner.py`](https://github.com/gabrielkmbo/parse-bench/blob/main/src/eval/runner.py) / `scoring.py` — async eval with three protocols (`full_doc / oracle_page / oracle_crop`), score_answer + page_recall + bbox_iou + diagnostic gaps.
- [`src/eval/pricing.py`](https://github.com/gabrielkmbo/parse-bench/blob/main/src/eval/pricing.py) — token+USD accounting (added 2026-04-13 per CLAUDE.md changelog).
- HF dataset `gabrielbo/parser-bench` ~1.5k rows with embedded images, matches schema.
- Baseline results in the PDF slide deck:
  - GPT-5.4 `full_doc 48.6% → oracle_crop 59.4%` (+10.8 pt localization gap)
  - Gemini 3.1 Pro Preview `42.0 → 50.3` (+8.3)
  - Claude Opus 4.6 `29.8 → 43.2` (+13.4)
  - Cost: Claude full_doc $0.065/correct vs GPT-5.4 oracle_crop $0.010/correct → **~6× cost headroom** if agentic routing works.

### What FocusParse builds (gaps vs current state)

| Gap | FocusParse delivers |
|---|---|
| No tool-enabled protocol | `focus` protocol = workflow with budget + trajectory |
| No evidence-reward scoring (lazy-answer penalty) | `score_evidence_reward` wrapping parser-bench scorer |
| No trajectory log | `traces/*.jsonl` per run, SFT-ready |
| No multi-tier routing | `models/tiers.py` cheap→frontier escalation per stage |
| No HF + NFS unified dataset loader | `dataset/loader.py` (HF streaming default, NFS fallback) |
| No evidence-packet abstraction | `evidence/packet.py` as first-class API |
| No HTML per-example report | `eval/report.py` |
| No coding-driven high-res zoom | `tools/run_python.py` sandboxed exec |

---

## 2. Desired end state

A repo where you can run:

```bash
uv run focus eval \
  --split dev --limit 200 \
  --tier balanced \          # cheap planner+router, frontier reasoner
  --budget tokens=120k,tool_calls=12,crops=8 \
  --export-traces results/runs/<ts>/traces.jsonl
```

…and get back:

1. A JSON results file with `accuracy`, `page_recall_mean`, `bbox_iou_mean`, **`evidence_reward_mean`**, **`lazy_answer_rate`**, tokens, USD, latency — broken out by `question_family`, `stress_type`, `difficulty`, and `tier`.
2. An HTML report per example with: the question, the predicted answer, the trajectory (tool calls in order), the crops viewed, the cited vs gold boxes overlaid on page thumbnails, and per-step token/cost.
3. A clean `traces.jsonl` with one line per example: `{example_id, question, plan, steps: [{action, args, observation, tokens}], final: {answer, citations, reward}}`.
4. **Reproducible** baseline rows matching parser-bench's published numbers (±1%) to prove we haven't accidentally improved the evaluand.

### Success criteria for v1

- **Quality:** on parser-bench `dev` split, FocusParse `balanced` tier beats its own `simple` single-shot baseline by **≥ +6 pts accuracy** at **≤ 0.7×** cost-per-correct.
- **Citation grounding:** `evidence_reward_mean` ≥ 0.35 (correct answer + supported bbox with IoU ≥ 0.3).
- **Lazy-answer rate:** < 10% (answers correct without any tool call or without predicted bboxes).
- **Reproducibility:** baseline `simple` agent matches parser-bench's published full_doc numbers within ±1 pt.

---

## 3. Architecture

### 3.1 State machine (workflows-py)

```
                         ┌────────────┐
      question + doc ──▶ │  PLANNER   │  cheap LLM classifies question family,
                         │ (cheap)    │  evidence types, budget class, routing policy
                         └─────┬──────┘
                               ▼
                         ┌────────────┐
                         │PAGE ROUTER │  (1) PDF text FTS, (2) OCR FTS,
                         │ (cheap)    │  (3) visual rerank w/ vdr-2b-multi (optional),
                         └─────┬──────┘  (4) DocLens-style repeated sampling union
                               ▼  top-k pages + reason codes
                         ┌────────────┐
                         │ LOCALIZER  │  deterministic first: HF layout endpoint
                         │ (det + opt │  + OCR token anchors + question-family priors
                         │  LLM rerank│  → ranked candidate region set per page
                         └─────┬──────┘
                               ▼
                         ┌────────────┐   ◀── loop / budget guard
                         │ INSPECTOR  │  ReActAgent with tool belt:
                         │ (mid/frontier│   - inspect_region(mode=image|element|region)
                         │  as needed)│   - expand_context (graph-aware margin expand)
                         └─────┬──────┘   - get_text_layer (deterministic PDF text)
                               │           - chart_to_table (specialist, optional)
                               │           - run_python (coding zoom, safe sandbox)
                               ▼
                         ┌────────────┐
                         │  PACKAGER  │  EvidencePacket[] = {page thumb + crop +
                         │ (det)      │  OCR snippet + linked neighbors + provenance}
                         └─────┬──────┘
                               ▼
                         ┌────────────┐
                         │  REASONER  │  frontier LLM sees ONLY packets, not full doc
                         │ (frontier) │  produces answer + cited region_ids
                         └─────┬──────┘
                               ▼
                         ┌────────────┐
                         │  VERIFIER  │  second pass: is answer supported?
                         │ (mid)      │  if no → escalate / expand / abstain
                         └─────┬──────┘
                               ▼
                      answer + citations +
                      trajectory + telemetry
```

### 3.2 Why workflows-py (skeptical check)

`workflows-py` gives us **async `@step`s, typed events, parallelism, and checkpointing for free** — the PDF's concerns about "sequential runtime killing latency" land exactly here. Alternatives we rejected:

- **Custom state machine:** saves one dependency, costs us checkpointing, event visualization, and integration with `ReActAgent`. Not worth it.
- **LangGraph:** heavier, and we'd lose native `ReActAgent` + `TokenCountingHandler` + `CitationQueryEngine` from llama_index.
- **AutoGen / CrewAI:** multi-agent-first framing contradicts your explicit "orchestrated pipeline, not swarm" direction.

**Risk we accept:** coupling to the LlamaIndex ecosystem. Mitigation: every `@step` contains pure logic; only the outer `Workflow` wiring depends on `workflows-py`. Ripping it out later is a 1-day job.

### 3.3 Controlled parallelism

Per your PDF's "parallelism vs sequential" section:

- **Parallelize**: page text indexing, per-page region proposals after routing, alternate-answer sampling, verifier-first-pass text retrieval.
- **Sequential**: planner, final region choice, context expansion decision, verifier escalation.

Implementation: use `workflows-py` `Event` fan-out for region proposals (`emit N ProposeRegionEvent, collect via ctx.collect_events`), keep the verifier loop serial.

### 3.4 Multi-tier model routing

```
configs/default.yaml:
  tiers:
    cheap:     { provider: gemini,    model: gemini-3.1-flash-preview }
    mid:       { provider: anthropic, model: claude-haiku-4-5 }
    frontier:  { provider: openai,    model: gpt-5.4 }
  roles:
    planner:   cheap
    router:    cheap
    localizer_rerank: mid
    reasoner:  frontier
    verifier:  mid
    # escalation: any role can escalate one tier up when `confidence < 0.5`
```

Escalation is **per-stage**, never pipeline-wide — the #1 lesson from your DocLens/AgenticOCR notes.

---

## 4. Repo scaffold

### 4.1 Directory layout (monorepo)

```
FocusParse/
├── .claude/
│   ├── settings.json              # Claude Code harness config (permissions, MCP, default models)
│   ├── agents/                    # project-scoped subagent definitions
│   │   ├── pipeline-engineer.md
│   │   ├── tools-engineer.md
│   │   ├── trace-exporter.md
│   │   └── eval-runner.md
│   └── memory/
│       └── MEMORY.md              # running agent memory — agents keep this current
├── .mcp.json                      # project MCP servers (HF, filesystem)
├── .env.example                   # template; real .env is gitignored
├── .gitignore
├── README.md                      # 1-page overview + quickstart
├── CLAUDE.md                      # minimalist operational notes (see §4.3)
├── pyproject.toml                 # uv-managed, py ≥ 3.11, ruff line-length 100
├── configs/
│   └── default.yaml               # tiers, roles, budgets, HF/NFS paths
├── src/focusparse/
│   ├── __init__.py
│   ├── pipeline/                  # workflow + @step modules
│   │   ├── workflow.py            # top-level FocusWorkflow
│   │   ├── events.py              # typed events flowing between steps
│   │   ├── planner.py             # question-family classifier + budget setter
│   │   ├── router.py              # page routing (FTS + optional vdr-2b rerank)
│   │   ├── localizer.py           # layout + OCR anchor fusion
│   │   ├── inspector.py           # ReActAgent tool loop
│   │   ├── expander.py            # graph-aware context expansion
│   │   ├── reasoner.py            # packet-only answerer w/ CitationQueryEngine
│   │   └── verifier.py            # support checker + escalation/abstain
│   ├── tools/                     # FunctionTool-wrapped primitives
│   │   ├── inspect_region.py      # unified zoom/crop/OCR tool (3 modes)
│   │   ├── expand_context.py
│   │   ├── get_text_layer.py      # deterministic PDF text span retrieval
│   │   ├── chart_to_table.py      # specialist, optional, high-commit
│   │   ├── run_python.py          # sandboxed exec for coding-zoom
│   │   └── layout_detect.py       # HF endpoint client (reuses parser-bench URL)
│   ├── evidence/
│   │   ├── packet.py              # EvidencePacket dataclass (contract)
│   │   └── graph.py               # lightweight per-question evidence graph
│   ├── models/
│   │   ├── base.py                # ModelClient protocol (predict, predict_batch, count_tokens)
│   │   ├── anthropic.py
│   │   ├── openai.py
│   │   ├── gemini.py
│   │   └── tiers.py               # tier routing + escalation policy
│   ├── retrieval/
│   │   ├── text_index.py          # sqlite FTS over PDF-text + OCR text
│   │   └── visual_rerank.py       # vdr-2b-multi-v1 reranker (HF inference endpoint)
│   ├── cache/
│   │   └── store.py               # content-addressed disk cache: crops, OCR, embeddings
│   ├── dataset/
│   │   ├── loader.py              # HF streaming (default) + local parser-bench fallback
│   │   └── nfs.py                 # llama-nfs rsync helpers (reused from parser-bench)
│   ├── eval/
│   │   ├── harness.py             # runs a workflow over a benchmark slice
│   │   ├── scoring.py             # wraps parser-bench scorer + evidence_reward
│   │   ├── metrics.py             # aggregates + diagnostic gaps + lazy_answer_rate
│   │   └── report.py              # HTML per-example report w/ trajectory viz
│   ├── traces/
│   │   ├── recorder.py            # in-workflow trajectory capture
│   │   └── export.py              # SFT-ready JSONL writer
│   └── cli/
│       ├── focus.py               # `focus eval`, `focus run`, `focus export-traces`, `focus report`
│       └── __main__.py
├── scripts/                       # one-off workflows not in the main CLI
│   ├── reproduce_baselines.py
│   ├── compare_tiers.py
│   └── fetch_nfs_processed.py
├── tests/
│   ├── test_workflow.py           # unit tests w/ mocked tools
│   ├── test_tools.py              # each tool, against fixture PDF
│   ├── test_scoring.py            # evidence_reward edge cases
│   ├── test_dataset_loader.py
│   └── fixtures/
│       └── tiny_datasheet.pdf     # 5-page tiny PDF for CI
├── plans/
│   └── 2026-04-13-focusparse-agentic-pipeline.md   ← this file
└── results/                       # gitignored run outputs
    └── .gitkeep
```

**Why this shape:** every top-level dir has a single responsibility; `pipeline/` matches the state machine 1:1 so readers can navigate from the diagram to code; `tools/` stays small and strong; `cache/`, `traces/`, and `results/` are write-only sinks; `plans/` is the research log.

### 4.2 `pyproject.toml` (skeleton)

```toml
[project]
name = "focusparse"
version = "0.1.0"
description = "Agentic evidence-localization pipeline for high-resolution financial and datasheet QA"
requires-python = ">=3.11"
readme = "README.md"
license = { text = "Apache-2.0" }
authors = [{ name = "Gabriel Bo" }]

dependencies = [
  # Orchestration
  "llama-index-workflows>=0.3.0",
  "llama-index-core>=0.12.0",
  "llama-index-agent-react>=0.1.0",
  # Model SDKs (free to swap per tier)
  "anthropic>=0.40.0",
  "openai>=1.55.0",
  "google-genai>=0.3.0",
  # PDF + image
  "pymupdf>=1.24.0",
  "pillow>=10.0.0",
  "pytesseract>=0.3.10",
  # Data
  "datasets>=3.0.0",              # HF streaming
  "pyarrow>=18.0.0",
  "pydantic>=2.9.0",
  "pyyaml>=6.0",
  # Retrieval
  "rank-bm25>=0.2.2",             # optional sparse fallback
  "sqlite-utils>=3.37",           # FTS convenience
  # Telemetry / reports
  "rich>=13.9.0",
  "jinja2>=3.1.0",                # HTML reports
  # HTTP
  "httpx>=0.27.0",
  "tenacity>=9.0.0",              # retry layer for HF endpoints
]

[project.optional-dependencies]
liteparse = ["llamaindex-liteparse"]          # optional, if Python subpkg is usable
llamacloud = ["llama-cloud>=0.1.0"]           # paid LlamaParse/LlamaExtract adapter
visual-rerank = ["sentence-transformers>=3.0", "torch>=2.4"]  # for local vdr-2b
chart-tools = ["matplotlib>=3.9", "numpy>=2.0", "scipy>=1.14"]  # run_python sandbox libs
dev = ["ruff>=0.7", "pytest>=8.0", "pytest-asyncio>=0.24", "mypy>=1.11"]

[project.scripts]
focus = "focusparse.cli.focus:main"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### 4.3 `CLAUDE.md` (minimalist — target < 150 lines)

Contents (skeleton — actual content written during implementation):

- **What this repo does** — 3 sentences.
- **Read first:** `README.md` (product overview), `plans/` (active plan).
- **Primary workflow:** `uv sync`, `uv run focus eval ...`.
- **Env / secrets:** `.env` keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `HF_TOKEN`, `LLAMA_CLOUD_API_KEY` (optional).
- **Model tiers:** `configs/default.yaml#tiers` — change here, not in code.
- **HF endpoints used:**
  - Layout: `https://jqkx3k3gn4ciymvi.us-east-1.aws.endpoints.huggingface.cloud` (RT-DETRv2 via parser-bench) — requires `HF_TOKEN`.
  - Visual rerank: `llamaindex/vdr-2b-multi-v1` (via HF inference endpoint; local fallback under `[visual-rerank]` extra).
- **NFS (processed docs):** `llama-nfs:/home/osx-user/shared-experiments/llamacloud-bench-ci/data/parser-bench/` — mirror parser-bench's contract. Use `focusparse.dataset.nfs.rsync_pull(doc_id)`.
- **What not to do:** do **not** modify `parser-bench` source; do **not** vendor `liteparse` or `llama_index` source.
- **OSS training (future):** trajectories go in `results/runs/<ts>/traces.jsonl` — structured for later Qwen3-VL SFT/GRPO in a separate `FocusTrain` repo. Recipe notes in `.claude/memory/MEMORY.md` under "Training plan".
- **Keeping this file current:** after substantive changes (new pipeline stage, new model tier, new env var, new HF endpoint, schema change), append **one line** to `## Changelog` at the bottom: `YYYY-MM-DD — imperative summary`. Skip for typos.
- **Changelog** section (bootstrapped with the init commit line).

Target: any new agent can run the pipeline end-to-end using only this file.

### 4.4 `.claude/memory/MEMORY.md` (agent-updated running notes)

Structured as a **growing append-only log** with dated sections. Initial seed includes:

```markdown
# FocusParse — Agent Memory

> Agents: keep this file current. Add a dated entry any time you learn something
> that would not be obvious to the next agent from the code alone — model quirks,
> debugging gotchas, tier-routing decisions, trajectory schema evolutions.
> Structure: one **## YYYY-MM-DD — topic** heading per discovery, newest at top.

## Standing context

- **Benchmark:** `gabrielbo/parser-bench` on HF. Schema: `BenchmarkExample` in parser-bench.
- **Baseline numbers to beat (2026-04-13):** GPT-5.4 full_doc 48.6% / oracle_crop 59.4%.
- **Target v1 milestone:** `focus balanced` tier ≥ +6 pts accuracy at ≤ 0.7× cost vs `focus simple` on dev split.
- **Do not modify parser-bench** from this repo.

## Training plan (tracked here, not built here)

- Recipe: AgenticOCR-style — SFT on teacher trajectories filtered by dual threshold
  (coverage recall + IoU); then GRPO with reward = answer × IoU × coverage
  − spurious_box_penalty − overlap_penalty − lazy_full_page_penalty.
- Base model: Qwen3-VL-4B. Serving: Modal for training, deploy to HF inference endpoint.
- Trajectories to collect: everything from `focus eval --tier frontier` on the dev split
  plus hard negatives where parser-bench teacher + verifier disagreed.
- Training repo (future): `FocusTrain` — consumes `traces/*.jsonl` from here.

## Model quirks (living)

- Gemini 3.x: set `thinking_budget ≥ 1024` or visible response is empty (per parser-bench PDF).
- GPT-5.x: uses `max_completion_tokens`, not `max_tokens`.
- Claude Opus 4.6 full_doc accuracy lags on finance charts — prefer GPT-5.4 as reasoner tier.

## Known sharp edges

- Layout HF endpoint (jqkx3…) can return a single full-page bbox stub on failure —
  the signal is "whole page crops only". Check `HF_TOKEN` and backoff logs first.
- NFS path uses SSH `llama-nfs` host alias — must exist in `~/.ssh/config`.
- HF dataset revision is **not** pinned yet (per plan decision); benchmark is still
  being hardened (contact-sheet bbox fix + 300dpi oracle crops, PDF slides). Re-run
  baselines whenever the dataset advances.
```

Agents update this file via the same convention as CLAUDE.md: newest first, one section per substantive discovery.

### 4.5 `.claude/settings.json` (Claude Code harness config)

Per your choices (a) default models per role, (b) agent definitions, (d) MCP — **no hooks**:

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "Read(./*)",
      "Write(./src/**)",
      "Write(./tests/**)",
      "Write(./scripts/**)",
      "Write(./configs/**)",
      "Write(./plans/**)",
      "Write(./.claude/**)",
      "Bash(uv *)",
      "Bash(git *)",
      "Bash(pytest *)",
      "Bash(ruff *)"
    ],
    "deny": [
      "Bash(rm -rf *)",
      "Bash(git push --force*)",
      "Write(./.env)",
      "Write(./uv.lock)"
    ]
  },
  "env": {
    "FOCUSPARSE_TIER_PLANNER": "cheap",
    "FOCUSPARSE_TIER_ROUTER": "cheap",
    "FOCUSPARSE_TIER_REASONER": "frontier",
    "FOCUSPARSE_TIER_VERIFIER": "mid"
  },
  "statusLine": {
    "type": "command",
    "command": "uv run python -m focusparse.cli.focus status --short"
  }
}
```

The four `FOCUSPARSE_TIER_*` env vars are read by `configs/default.yaml` to override per role — lets you flip a whole tier via `.claude/settings.json` without editing code.

### 4.6 `.mcp.json` (project MCP servers)

```json
{
  "mcpServers": {
    "huggingface": {
      "command": "npx",
      "args": ["-y", "@huggingface/mcp-server"],
      "env": { "HF_TOKEN": "${HF_TOKEN}" }
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "${PWD}"]
    }
  }
}
```

HF MCP lets agents hit the `llamaindex/` org, check dataset revisions, and pull model cards without leaving the session. Filesystem MCP is scoped to repo root.

### 4.7 `.claude/agents/*.md` — project subagents

Four tight-scoped subagents. Each is a markdown file with frontmatter (name, description, tools, model).

**`.claude/agents/pipeline-engineer.md`**
```yaml
---
name: pipeline-engineer
description: Implements or modifies workflow @step modules (planner, router, localizer, inspector, expander, reasoner, verifier). Owns `src/focusparse/pipeline/`.
tools: Read, Write, Edit, Grep, Glob, Bash
model: sonnet
---
You own `src/focusparse/pipeline/`. Every step must:
- Read from typed events, write typed events (no dict-shaped payloads).
- Record a `TrajectoryStep` via `focusparse.traces.recorder`.
- Respect the per-stage tier from `configs/default.yaml` — never hard-code models.
- Be unit-testable with mocked tools (see `tests/test_workflow.py` for pattern).
Read `plans/2026-04-13-focusparse-agentic-pipeline.md` before making structural changes.
```

**`.claude/agents/tools-engineer.md`**
```yaml
---
name: tools-engineer
description: Implements or modifies FunctionTool-wrapped primitives. Owns `src/focusparse/tools/` including the sandboxed Python executor.
tools: Read, Write, Edit, Grep, Glob, Bash
model: sonnet
---
You own `src/focusparse/tools/`. Rules:
- Every tool is a single `@FunctionTool.from_defaults` export with a Pydantic input schema.
- `inspect_region` has exactly three modes: image, element, region. Do not add a fourth without updating the plan.
- `run_python` runs in a subprocess with a time limit and an allowlist of imports
  (PIL, numpy, matplotlib.pyplot, scipy). Never eval model-authored code in-process.
- All tools hit the cache layer (`focusparse.cache.store`) via content-addressed keys
  before doing any real work.
```

**`.claude/agents/trace-exporter.md`**
```yaml
---
name: trace-exporter
description: Owns trajectory recording + JSONL export. Ensures the trace schema stays SFT-ready for the future FocusTrain repo.
tools: Read, Write, Edit, Grep, Glob
model: haiku
---
You own `src/focusparse/traces/`. The trace JSONL schema is the contract with FocusTrain — changing a field is a breaking change. Bump the `schema_version` in `export.py` and note it in `.claude/memory/MEMORY.md` when you do.
```

**`.claude/agents/eval-runner.md`**
```yaml
---
name: eval-runner
description: Runs evaluations, compares baselines, produces HTML reports. Owns `src/focusparse/eval/` and `scripts/reproduce_baselines.py`.
tools: Read, Write, Edit, Bash, Grep, Glob
model: sonnet
---
You own `src/focusparse/eval/`. Any new metric must:
- Be aggregated in `metrics.py` with per-split, per-family, per-stress-type breakdown.
- Be surfaced in `report.py` HTML output.
- Have at least one unit test in `tests/test_scoring.py`.
Keep the reproducibility check (baseline `simple` vs parser-bench published numbers ±1 pt) green at all times.
```

### 4.8 `.gitignore`

```
# python
__pycache__/
*.py[cod]
.venv/
.ruff_cache/
.pytest_cache/
.mypy_cache/

# env + secrets
.env
.env.local

# data + results (write-only sinks)
results/
data/
traces_out/
crops_cache/
hf_cache/
.hf_datasets_cache/

# os
.DS_Store

# editor
.vscode/
.idea/

# uv
# (keep uv.lock tracked)
```

`uv.lock` is tracked; `.env` never is (template at `.env.example`).

### 4.9 `.env.example`

```
# Model providers (at least one required)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=

# HuggingFace (required for layout endpoint + vdr-2b rerank + dataset streaming)
HF_TOKEN=

# Optional: LlamaCloud (LlamaParse / LlamaExtract baseline row)
LLAMA_CLOUD_API_KEY=

# Optional: layout endpoint override (default uses parser-bench's endpoint)
FOCUSPARSE_LAYOUT_ENDPOINT_URL=

# Optional: Tesseract binary path (default autodiscover via $PATH)
TESSERACT_CMD=
```

---

## 5. Implementation phases

Each phase has **automated** and **manual** success criteria. Pause after each phase for manual check before proceeding.

### Phase 1 — Repo scaffold + baseline reproduction

**What this phase accomplishes:** a runnable skeleton where `focus eval --agent simple` reproduces parser-bench's published numbers within ±1 pt, proving we haven't changed the evaluand.

#### Changes

1. Initialize the files listed in §4.1–4.9.
2. `src/focusparse/dataset/loader.py` — `BenchmarkLoader` class:
   - `.from_hf(split="dev", revision=None, streaming=True)` — default path.
   - `.from_local(parser_bench_root)` — reads `data/candidates/*.jsonl` + `data/processed/<doc>/images/`.
   - Returns `Iterator[BenchmarkExample]` using parser-bench's pydantic schema (we depend on parser-bench as a git submodule **or** copy just `schema.py` — **decision point, ask user before implementing** — see §8.1).
3. `src/focusparse/dataset/nfs.py` — port `_rsync_pull` / `_rsync_push` helpers from parser-bench's `scripts/run_generate.py` (read-only port, no modification of parser-bench).
4. `src/focusparse/eval/scoring.py` — import parser-bench scorer or reimplement `score_answer` + `_bbox_iou` + `page_recall` minimally (decision depends on §8.1).
5. `src/focusparse/pipeline/workflow.py` — stub `FocusWorkflow` with a single `simple` agent step that sends all page images to a chosen backend (matches parser-bench's `SimpleAgent`).
6. `src/focusparse/cli/focus.py` — `focus eval`, `focus status` subcommands.
7. `scripts/reproduce_baselines.py` — runs `simple` agent on dev split with each of the three backends and diffs against a pinned `parser-bench/results/baselines_2026-04-13.json`.

#### Automated verification

- [ ] `uv sync` runs clean on Python 3.11.
- [ ] `uv run ruff check src/ tests/` passes.
- [ ] `uv run pytest tests/test_dataset_loader.py` passes (streams 5 examples, validates schema).
- [ ] `uv run focus status` prints tier config from env + YAML.
- [ ] `uv run focus eval --agent simple --backend gemini --model gemini-3.1-pro-preview --split dev --limit 30` produces a results JSON matching parser-bench's dev numbers for Gemini within ±1 pt.

#### Manual verification

- [ ] HTML report renders for the 30-example run; cited bboxes are visible as overlays on page thumbnails.
- [ ] `.env.example` captures every real secret we used.
- [ ] CLAUDE.md can be handed to a fresh agent and they can reproduce the baseline run from it alone.

**Pause for manual confirmation before proceeding.**

---

### Phase 2 — Lens workflow v1 (planner + router + localizer + inspector + reasoner + verifier)

**What this phase accomplishes:** the full state machine running end-to-end with real tools, real tier routing, and real trajectory capture.

#### Changes

1. `src/focusparse/pipeline/events.py` — typed events:
   - `QuestionEvent(example)`
   - `PlanEvent(question_family, evidence_types, budget, policy)`
   - `PagesEvent(candidate_pages: list[{page, score, reason}])`
   - `RegionsEvent(candidate_regions: list[Region])`
   - `EvidenceEvent(packets: list[EvidencePacket])`
   - `AnswerEvent(answer, citations, confidence)`
   - `VerdictEvent(supported: bool, reason, next_action)`
2. `planner.py` — one cheap-tier LLM call; Pydantic output schema with `question_family ∈ parser_bench QuestionFamily enums`, `budget: Budget`, `policy: RoutingPolicy`.
3. `router.py` — hybrid: sqlite FTS over PDF+OCR text (from `document.json`) ∪ optional `vdr-2b-multi-v1` visual rerank ∪ DocLens-style 3×-sampled union. Returns top-k=5 pages + reason codes.
4. `localizer.py` — deterministic fusion of (a) HF layout endpoint boxes, (b) OCR token anchors matching question keywords, (c) question-family priors (e.g. chart+legend+axis for `axis_value_interpolation`). No LLM call unless ambiguity > threshold.
5. `inspector.py` — `ReActAgent` with tool belt (see Phase 3 tools); `TokenCountingHandler` wrapped as budget guard (raises `BudgetExceeded` → graceful stop with collected packets).
6. `expander.py` — graph-aware: for each inspected region, attach linked neighbors (caption, footnote, legend, header row) via parser-bench's `evidence_relations` if present; otherwise heuristic margin-expansion (top 30px for table headers, bottom 50px for footnotes).
7. `packager.py` — builds `EvidencePacket[]`: page thumbnail + highlighted bbox + local crop + wider context crop + OCR snippet + linked neighbor crops + provenance (which tool produced it).
8. `reasoner.py` — frontier-tier LLM; prompt sees ONLY packets (no full pages); uses `CitationQueryEngine`-style "Source N:" markers.
9. `verifier.py` — mid-tier LLM; binary support check + reason; returns one of `{accept, retry_localization, expand_context, abstain, escalate_reasoner}`.
10. `traces/recorder.py` — collects each step's `TrajectoryStep(action, args, observation_summary, tokens_in, tokens_out, latency_ms, usd)` into a `RunTrace`.

#### Automated verification

- [ ] `uv run pytest tests/test_workflow.py` passes — mocked tools, asserts the full state machine runs to completion.
- [ ] `uv run focus eval --agent focus --tier balanced --backend openai --model gpt-5.4 --split dev --limit 20` completes without BudgetExceeded on ≥ 80% of examples.
- [ ] Every run produces a `traces.jsonl` with ≥ 1 tool call per example.
- [ ] Verifier escalation triggers on at least 1 of 20 examples (sanity check that the branch is wired).

#### Manual verification

- [ ] Inspect 5 random HTML reports: evidence packets look correct, citations overlay the gold bboxes, trajectory is human-readable.
- [ ] Claude reasoner with packets beats Claude full_doc on the same 20 examples (local sanity check).

**Pause for manual confirmation.**

---

### Phase 3 — Tools layer

**What this phase accomplishes:** the five tools in `src/focusparse/tools/` become robust, cached, and sandboxed, including the coding-driven zoom.

#### Changes

1. **`inspect_region`** — three modes, Pydantic input schema:
   ```python
   class InspectInput(BaseModel):
       page: int
       bbox_norm: tuple[float, float, float, float]  # normalized [0,1]
       mode: Literal["image", "element", "region"]
       dpi: int = 300
       rotation: int = 0
       expansion: Literal["none", "default", "aggressive"] = "default"
   ```
   - `image`: crop + return PNG bytes (no OCR, cheapest).
   - `element`: crop + Tesseract OCR + return text + crop.
   - `region`: crop + sub-layout detection (HF endpoint on crop) + OCR per sub-element + return structured sub-regions.

2. **`expand_context`** — given a region, return its linked neighbors from the evidence graph (if known) or heuristic margin-expanded neighbors (if not).

3. **`get_text_layer`** — deterministic PDF text span retrieval via PyMuPDF. Crucial for beating "OCR-only" adversarial filters in parser-bench.

4. **`chart_to_table`** *(optional, `[chart-tools]` extra)* — crop → numpy peak detection on gridlines + axis OCR → CSV-shaped table. Explicitly low-confidence by default; router uses it only when question family is `axis_value_interpolation` or `candlestick_ohlc_extraction`.

5. **`run_python`** — the coding-zoom tool. **Critical design — this is the high-res zoom mechanism you called out in answer #6.**
   - Runs in a **subprocess** (not `exec` in-process) with a 15s CPU/wall-time limit via `resource.setrlimit`.
   - Pre-imported allowlist: `PIL.Image`, `numpy as np`, `matplotlib.pyplot as plt`, `scipy.ndimage`. Nothing else.
   - Input: code string + list of `image_refs` (content-addressed IDs from prior tool calls). The sandbox receives the actual bytes, the model only knows IDs.
   - Output: text stdout + optional new image (assigned a new `image_ref`) that the model can re-inspect via `inspect_region` on a "virtual page".
   - **This is where high-resolution zoom happens**: the model can `img.crop(tight_box).resize((2*w, 2*h), LANCZOS)` to super-sample a 10-pixel-tall axis label at 4× on the pristine 300 DPI source.
   - Security caveat: this is sandboxing, not isolation. Acceptable for a research repo; document the threat model in `CLAUDE.md`.

6. **`layout_detect`** — thin HTTP client for parser-bench's HF layout endpoint, with retry + stub-fallback detection (log a warning, don't silently succeed).

7. **`cache/store.py`** — content-addressed disk cache keyed on `sha256(pdf_hash, page, bbox_quant, dpi, mode)`. Every tool checks cache first. Cache hits are free and deterministic across runs.

#### Automated verification

- [ ] `uv run pytest tests/test_tools.py` — per-tool unit tests against `fixtures/tiny_datasheet.pdf`.
- [ ] `test_run_python_sandbox_timeout` — confirms a `while True: pass` payload is killed at the wall-time limit.
- [ ] `test_run_python_sandbox_import_denied` — confirms `import os; os.system(...)` is blocked.
- [ ] Cache hit rate on a re-run of the same 20 examples ≥ 90% for inspect_region calls.

#### Manual verification

- [ ] Run the workflow on 3 datasheet examples with known tiny-text evidence (e.g. `min_typ_max_disambiguation`). Confirm the model uses `run_python` to super-sample and that the super-sampled crop appears in the HTML report.
- [ ] `chart_to_table` produces a plausible table on one finance chart example.

**Pause for manual confirmation.**

---

### Phase 4 — Evidence-aware scoring + HTML report

**What this phase accomplishes:** the harness penalizes lazy answers and produces a publishable HTML report per run.

#### Changes

1. `eval/scoring.py::score_evidence_reward(prediction, example)`:
   ```
   if len(prediction.tool_calls) == 0 or len(prediction.predicted_bboxes) == 0:
       return 0.0
   answer_component = score_answer(prediction, example)                # 0..1
   page_component   = page_recall(prediction.predicted_pages, example) # 0..1
   box_component    = max_iou_over_alternates(prediction, example)     # 0..1, uses alternate_bboxes
   lazy_penalty     = 1.0 if largest_crop_area_ratio > 0.6 else 0.0    # AgenticOCR "lazy full-page" flag
   return answer_component * page_component * box_component - 0.2 * lazy_penalty
   ```
2. `eval/metrics.py` — add `evidence_reward_mean`, `lazy_answer_rate`, `tool_calls_mean`, `pixels_returned_mean`, `usd_per_correct`; surface them in DocLens-style diagnostic-gaps breakdown.
3. `eval/report.py` — Jinja2 HTML template:
   - One page per example: question, predicted answer, gold, reward breakdown.
   - Page thumbnails with gold bboxes (green) + predicted bboxes (blue) + inspected crops (orange).
   - Trajectory table: step | tool | args | obs summary | tokens | latency | cost.
   - Top-level index page with aggregate table (accuracy / evidence_reward / USD by family × tier).

#### Automated verification

- [ ] `uv run pytest tests/test_scoring.py::test_lazy_answer_zero_reward` passes.
- [ ] `uv run pytest tests/test_scoring.py::test_perfect_answer_full_reward` passes.
- [ ] `uv run focus report results/runs/<ts>/` produces `index.html` + per-example pages.

#### Manual verification

- [ ] Spot-check 3 lazy-answer examples: the HTML clearly shows the penalty and why.
- [ ] Spot-check 3 high-reward examples: gold + predicted bboxes overlap visibly.

---

### Phase 5 — Multi-tier sweep + LlamaParse baseline

**What this phase accomplishes:** publishable comparison table across tiers and external doc parsers.

#### Changes

1. `scripts/compare_tiers.py` — runs `focus simple` × 3 frontier models, then `focus balanced` × 3 tier mixes, then `focus cheap_only`, all on the same dev slice; produces one markdown + HTML table.
2. `src/focusparse/tools/llamaparse_adapter.py` — behind `[llamacloud]` extra; wraps `llama_cloud.parsing.parse(pdf)` and exposes it as a drop-in replacement for the localizer+inspector chain (you get `{pages, regions, markdown}` from LlamaParse instead of our own pipeline). This is the external comparator row.
3. `scripts/reproduce_baselines.py` — extend to include LlamaParse row.

#### Automated verification

- [ ] `uv run python scripts/compare_tiers.py --limit 100` completes and writes `results/runs/<ts>/comparison.md`.
- [ ] Table contains rows for: `simple × {claude, gpt-5.4, gemini-3.1-pro}`, `focus balanced`, `focus cheap_only`, `focus + llamaparse` (if key present).

#### Manual verification

- [ ] `focus balanced` row shows **+6 pts accuracy ≥ at ≤ 0.7× cost-per-correct** vs `simple gpt-5.4` on dev split (success criterion).
- [ ] Comparison table is readable and matches the baseline numbers from the PDF slide deck (for the `simple` rows).

---

### Phase 6 — Trajectory export for SFT (no training code)

**What this phase accomplishes:** trajectory JSONL that the future `FocusTrain` repo can SFT Qwen3-VL on.

#### Changes

1. `src/focusparse/traces/export.py` — `export_sft_jsonl(run_dir, out_path, filter: TrajectoryFilter)`:
   - Filter by answer correctness (keep only correct trajectories for SFT; keep mixed for GRPO).
   - Apply AgenticOCR dual-threshold filter: `coverage_recall ≥ 0.8` AND `iou ≥ 0.3`.
   - Schema:
     ```json
     {
       "schema_version": "1",
       "example_id": "...",
       "question": "...",
       "plan": { "family": "...", "budget": {...} },
       "trajectory": [
         { "role": "tool_call", "tool": "inspect_region", "args": {...},
           "obs_ref": "sha256:...", "obs_summary": "OCR: '0.56V ...'" }
       ],
       "final": { "answer": "...", "citations": [...] },
       "reward": { "answer": 1.0, "iou": 0.42, "coverage": 1.0, "total": 0.42 },
       "teacher_tier": "frontier"
     }
     ```
   - Mask tool outputs from loss targets per AgenticOCR (the consuming trainer does this; we just record a hint field).
2. `scripts/export_traces.py` CLI wrapper.
3. Document the schema in `.claude/memory/MEMORY.md` under "Training plan → trace schema v1" and note any bump to `schema_version` requires a migration note.

#### Automated verification

- [ ] `uv run focus export-traces results/runs/<ts>/` produces a JSONL with N ≥ filtered count matching the expected rate.
- [ ] `jq . results/runs/<ts>/traces.jsonl | head -1` shows a valid schema-v1 record.

#### Manual verification

- [ ] Open 3 traces; confirm they are self-contained (any `obs_ref` can be resolved from the per-run cache).

---

## 6. Testing strategy

### Unit tests

- `test_workflow.py` — state machine transitions + mocked-tool coverage.
- `test_tools.py` — each tool against `tiny_datasheet.pdf`; sandbox security tests for `run_python`.
- `test_scoring.py` — `score_evidence_reward` edge cases (no tool → 0, perfect → 1, lazy full-page → penalty, unanswerable abstain).
- `test_dataset_loader.py` — HF streaming + local fallback round-trip.
- `test_tiers.py` — tier routing picks the right provider; escalation bumps one tier.

### Integration tests

- `test_reproduce_baselines.py` (slow, `pytest -m slow`) — actually hits APIs on 10 dev examples with each backend and asserts within ±3 pts of pinned baseline.

### Manual testing steps

1. Fresh clone → `uv sync` → `cp .env.example .env` + fill → `uv run focus eval --limit 3` works.
2. HTML report opens in browser and is navigable.
3. Trajectory JSONL can be round-tripped back into `focus report` to re-render without re-running the API.

### Reproducibility guardrail

The baseline reproduction check is a **CI gate**, not just a phase-1 step. Any PR that changes `simple` agent behavior must update the pinned baseline JSON and include reasoning in the PR body.

---

## 7. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Parser-bench schema drift breaks FocusParse | Pin to a specific commit SHA in `pyproject.toml` as a git dependency once the benchmark stabilizes (deferred per answer #9). Track in MEMORY.md. |
| Workflows-py has no native budget primitive | Wrap `TokenCountingHandler` in a `BudgetGuard` that raises `BudgetExceeded` from inside any `@step`. |
| `run_python` sandbox escape | Subprocess + `resource.setrlimit` + import allowlist is "good enough" for a research repo. Document threat model. Never deploy FocusParse to accept untrusted questions. |
| HF layout endpoint stub fallback gives garbage | `layout_detect` raises on stub response (full-page single bbox) rather than silently succeeding; verifier step catches downstream. |
| Token-cost metrics lie (multi-turn agents drop usage) | Integration tests assert `prediction.tokens_in > 0` and `> 0` for every non-cached call. Run a known-cost smoke test daily. |
| LlamaParse adapter's output doesn't map to our evidence packet | Keep the adapter behind `[llamacloud]` extra; document the output shape in `CLAUDE.md`; when it fails, we still have the local pipeline. |
| Coding-zoom tool gets "gamed" — model writes code to skip inspection | `run_python` is logged with the same trajectory-step weight as any tool call; lazy-penalty applies; verifier also checks citations independently of code output. |
| Qwen3-VL training recipe changes (paper landscape moving) | We don't build training in FocusParse — keeping trajectory schema stable (`schema_version` bump is a breaking change) is all we need to future-proof. |
| vdr-2b-multi-v1 distribution shift on datasheets | Visual rerank is optional, behind `[visual-rerank]` extra, ablated separately. Default router is FTS-only. |

---

## 8. Open decisions

### 8.1 Parser-bench schema dependency — **DECIDED: (a) git submodule** (2026-04-13)

Submodule at `third_party/parser-bench/`; import via a `sys.path` shim in `src/focusparse/__init__.py`:
```python
from parser_bench.utils.schema import BenchmarkExample, BBox, Domain, StressType
```
SHA pinned at submodule-add time; bump explicitly when parser-bench advances.

### 8.2 Visual rerank default — **DECIDED: (c) skip for v1** (2026-04-13)

FTS-only router in Phase 2 (sqlite FTS over PDF + OCR text, DocLens-style repeated sampling union). Visual rerank becomes an ablation row in Phase 5 and will be gated on either an HF Inference Endpoint or local GPU decision at that point — **no local model loading in v1**. The `[visual-rerank]` extra and `visual_rerank.py` stub are created empty so the seam exists, but `router.py` never imports them in v1.

### 8.3 Layout endpoint ownership — **DECIDED: (c) + (a)** (2026-04-13)

Layout runs once per doc, cached on disk under `cache/layout/<doc_sha>.json`. Cache-miss calls hit the shared parser-bench HF endpoint rate-limited at ≤ 2 req/s with exponential backoff (lift parser-bench's retry policy).

### 8.4 HF dataset revision pinning

Deferred (per answer #9). `FOCUSPARSE_DATASET_REVISION` env var wired in `.env.example` so pinning is one config flip later.

---

## 9. /init plan (what Claude Code does on a fresh clone)

This is the "first 30 minutes" sequence a new agent follows after `git clone`:

1. **Read** `README.md`, then `CLAUDE.md`, then `plans/2026-04-13-focusparse-agentic-pipeline.md` (this file), then `.claude/memory/MEMORY.md`.
2. **Check env** — `focus status` prints a table of: required env vars present/missing, tier config, HF/NFS connectivity.
3. **Sync** — `uv sync` (including the `[dev]` extra).
4. **Smoke test** — `uv run focus eval --agent simple --backend gemini --model gemini-3.1-pro-preview --split dev --limit 3` (uses the smallest frontier model).
5. **Read MEMORY.md's top 3 entries** — always starts with the newest agent-written context.
6. **Report** — the agent's first message to the user should be:
   - "I've read the plan + memory. Active phase is **Phase X**. Last MEMORY.md entry: YYYY-MM-DD — '...'. I am ready to work on [next unchecked Phase-X item]."

This `/init` sequence is codified in `.claude/agents/eval-runner.md`'s preamble so any agent claiming that role follows it.

---

## 10. References

### Papers / products driving the design
- **AgenticOCR** (arXiv 2511.18329) — unified `image_zoom_and_ocr_tool`, GRPO reward with lazy/overlap/spurious penalties. We lift the tool design and reward shape.
- **DocLens** (in your notes) — extractor/answerer decomposition, page-navigator repeated sampling, answer sampler + adjudicator. We lift the decomposition and the verifier.
- **Gemini 3 Flash "Agentic Vision"** (Google blog, Nov 2025) — think–act–observe + code-as-vision-tool. We lift the `run_python` zoom tool.
- **FinChart-Bench / FinMME / DocVQA / OmniDocBench / olmOCR** — benchmark framing only; our benchmark is parser-bench.
- **DocLayNet / M6Doc** — informs that layout models drift off non-academic docs; motivates our deterministic fusion in `localizer.py`.

### Repos we consume (and **do not** modify)
- [`run-llama/workflows-py`](https://github.com/run-llama/workflows-py) — `pip install llama-index-workflows`; `from workflows import Workflow, step`.
- [`run-llama/llama_index`](https://github.com/run-llama/llama_index) — `from llama_index.core.agent.workflow import ReActAgent`, `FunctionTool`, `TokenCountingHandler`, `CitationQueryEngine`.
- [`run-llama/liteparse`](https://github.com/run-llama/liteparse) — TS-primary; we use it **only** via its npm CLI if/when we want render diversity. Optional.
- [`run-llama/llama-cloud-py`](https://github.com/run-llama/llama-cloud-py) — `pip install llama-cloud`; `LlamaCloud(api_key=...).parsing / .extraction`. Optional baseline adapter.
- [`gabrielkmbo/parse-bench`](https://github.com/gabrielkmbo/parse-bench) — read-only benchmark.
- [`huggingface.co/llamaindex/vdr-2b-multi-v1`](https://huggingface.co/llamaindex/vdr-2b-multi-v1) — optional visual reranker.
- [`huggingface.co/datasets/gabrielbo/parser-bench`](https://huggingface.co/datasets/gabrielbo/parser-bench) — primary eval input.

### Source-of-truth documents
- `plans/2026-04-13-focusparse-agentic-pipeline.md` (this file) — authoritative plan.
- `.claude/memory/MEMORY.md` — running discoveries.
- `CLAUDE.md` — minimalist operational card.

---

## 11. Next step after this plan is approved

I will begin **Phase 1** with three parallel tasks:
1. Scaffold all files in §4 (empty stubs where implementation hasn't started).
2. Wire `dataset/loader.py` + resolve §8.1 (parser-bench schema dependency) with your chosen option.
3. Get `focus eval --agent simple` reproducing Gemini baseline ±1 pt as the first green test.

**Nothing is written to code until you confirm the plan + answer §8.1 and §8.2.**
