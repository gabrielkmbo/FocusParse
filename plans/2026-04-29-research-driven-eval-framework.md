# Research-Driven Eval Framework — The Headline Table That Drives Everything

## Overview

Refocus FocusParse around producing **one headline table** that supports
**one causal research claim**: an evidence-localization-first agent harness
beats both base VLMs and generic ReAct agents on high-resolution
domain-specific document parsing (technical datasheets + finance docs),
with tool-count as a secondary independent variable that magnifies the
effect.

After we have the headline table filled with statistically-meaningful
numbers (n=148, 95% bootstrap CIs), implementation work shifts to
**iterating on the three hot stages — inspect, expand_context, and tool
usage** — using ablations on the same table to explain _why_ one row
wins. Appendix experiments (oracle protocols, tile-size sweep, model
swaps) contextualize the headline; they are not the conclusion.

### Development priority — FocusParse harness is the product (2026-04-29)

**The comparator methods (Base VLM, ReAct, Agent baseline) exist only to
make our claim measurable. They are not products. They get the minimum
implementation needed for a fair fight, then they freeze.** The bulk of
ongoing engineering effort goes into the FocusParse agentic harness:
the inspect / expand_context / tool stack, the planner / router /
verifier wiring around them, and the trajectory recording that supports
the future SFT pipeline.

Concrete budget guidance:

- **Phase 4 (build comparators):** ≤ 1 day total for ReAct + Agent baseline
  combined. Use existing libraries (LangChain / LlamaIndex). Do not
  optimize their prompts beyond a single readable iteration. Once they
  produce sane numbers, freeze them.
- **Phase 6 (iterate FocusParse):** open-ended. This is where weeks of
  engineering live. Every tool, every stage tweak, every ablation.
- **Rule of thumb:** if a change touches `src/focusparse/pipeline/{localizer,
inspector,expander}.py`, `src/focusparse/tools/*`, or the trajectory
  recorder, it's "core" work and gets full effort. If a change touches
  `react_agent.py` or `agent_baseline.py` and it's not a bug fix, ask
  whether it's worth time we'd otherwise spend on the harness.

## Current State Analysis

### What we already have

- `gabrielbo/parser-bench` 148-row canonical validation split (101 datasheet, 47 finance), materialized at `~/.cache/focusparse/hf_staging/`.
- Two working method endpoints: `simple/full_doc` (Base VLM analog) and `focus/focus_default` (Our agent harness analog), both validated at n=148:
  - `simple/full_doc`: 46.6% accuracy, $0.012/correct, bbox_iou=0.38
  - `focus/focus_default`: 41.2% accuracy, $0.018/correct, bbox_iou=**0.73**
- Five tools shipped: `inspect_region`, `get_text_layer`, `layout_detect`, `expand_context`, `run_python` (`src/focusparse/tools/`). `chart_to_table` is a stub.
- Scoring at parser-bench parity (`src/focusparse/eval/scoring.py`) — `simple/full_doc` reproduces parser-bench's published GPT-5.4 baseline within 2pp.
- Eval infrastructure: `scripts/run_hf_eval.py` + `scripts/run_hf_matrix.py` + `scripts/rescore_predictions.py`.
- Phase-3 toggles: `--auto-zoom`, `--use-evidence-graph`, `--max-retries N` — wired but default off pending A/Bs at n≥30.

### Key Discoveries

- Domain field is built into `BenchmarkExample` (`domain ∈ {DATASHEET, FINANCE}`), so per-domain aggregation is one bucket-by-key away (`src/focusparse/eval/metrics.py`).
- Reasoner model is GPT-5.4 (frontier tier) by default; tier-router lets us swap per-stage without code changes. Model-swap ablations are config-only.
- Existing protocols (`full_doc / oracle_page / oracle_crop / tiled_2/4/8up / focus_default`) already work end-to-end. The new `agentic_multi_page` protocol replaces `tiled_4up` as the headline input.
- `simple/full_doc` and parser-bench's published GPT-5.4 baseline numbers will serve as a fixed external sanity-check row in the appendix, not the main claim.

### What we don't yet have

- **Per-domain aggregation**: current per-example records carry `domain` in the example but `aggregate()` doesn't bucket by it. ~30-line addition to `eval/metrics.py`.
- **ReAct loop method**: an LLM-driven think→act→observe agent with a configurable tool belt and no FocusParse stages. The independent variable that isolates "is the framework the variable, or just the tools?"
- **Generic agent baseline**: a ReActAgent built on a public framework (LangChain or LlamaIndex's `AgentRunner`) consuming the same tool sets — a comparator that says "FocusParse's stage-machine architecture is doing real work, not just any agent loop with the same tools."
- **`+2 tools` / `+4 tools` axis**: a CLI flag (`--tool-set minimal | full`) that's threaded through every method type so we can ablate tool count cleanly.
- **`agentic_multi_page` protocol** (b+c hybrid): each example exposes both a mixed-tile (2/4/8up varying) summary view AND the full page-list. Base VLM uses summary only; tool-using methods can navigate the full page-list via tools.
- **Bootstrap 95% CIs**: needed for n=47 finance cells where sampling noise can drown 3-5pp effects.

## Desired End State

A single command (`uv run focus headline-eval --output results/hf/headline/`) populates:

```
                          | Datasheets (n=101)     | Finance (n=47)
                          | accuracy | $/correct   | accuracy | $/correct
--------------------------|----------|-------------|----------|----------
Base VLM (no tools)       |   ?? ± ? |   $?.???    |   ?? ± ? |   $?.???
ReAct +2 tools            |   ?? ± ? |   $?.???    |   ?? ± ? |   $?.???
ReAct +4 tools            |   ?? ± ? |   $?.???    |   ?? ± ? |   $?.???
Agent baseline +2 tools   |   ?? ± ? |   $?.???    |   ?? ± ? |   $?.???
Agent baseline +4 tools   |   ?? ± ? |   $?.???    |   ?? ± ? |   $?.???
Our harness +2 tools      |   ?? ± ? |   $?.???    |   ?? ± ? |   $?.???
Our harness +4 tools      |   ?? ± ? |   $?.???    |   ?? ± ? |   $?.???
```

…where each cell carries 95% bootstrap CIs, and `matrix_summary.json` is structured for direct paper-table generation.

The implementation work AFTER this table is filled becomes about **shifting specific cells**, not about new features in the abstract:

- "Improve `expand_context` such that `Our harness +4 tools / Datasheets / accuracy` moves +X pp."
- "Add a chart-table specialist such that `Our harness +4 tools / Finance / $/correct` drops by Y%."
- Every PR's commit message gets the cell it's targeting.

### Success criteria for v1 of this framework

- **Headline table filled** with 7 method × 2 task × 2 metric cells (Base VLM has 1 variant; ReAct, Agent baseline, Our harness each have 2 tool-count variants → 7 rows).
- **CIs reported** at 95% via 1000-sample bootstrap on per-example records.
- **Reproducibility gate maintained**: appendix row showing `simple/full_doc` matches parser-bench's published GPT-5.4 baseline within ±2pp.
- **One causal claim defended**: at least one (method, tool-count) pair beats Base VLM by ≥ 5pp on at least one domain at non-overlapping CIs. If this fails, we have a paper about _why nothing works on this benchmark_, which is also publishable.

## What We're NOT Doing

- **Not abandoning the prior plans.** `plans/2026-04-13-focusparse-agentic-pipeline.md` Phase 5 (multi-tier sweep), `plans/2026-04-27-phase2-sota-leverage.md` items 3–5 (loop / rerank / graph), and `plans/2026-04-27-fix-baseline-accuracy.md` (already done) all stay live — they get **reframed as cells in this table or ablations of this table**.
- **Not making oracle protocols the main story.** `oracle_page` and `oracle_crop` go to the appendix as "ceiling" measurements that show how much the agent's _navigation_ is costing vs an oracle that knows where to look.
- **Not changing the reasoner model in the headline row.** Base VLM line uses GPT-5.4. Model swap is an appendix experiment that explains the result, not constitutes it.
- **Not running tiny single-doc smokes as the headline.** n=148 with bootstrapped CIs is the smallest stat-meaningful unit. Single-doc runs become CI debugging only.
- **Not implementing `chart_to_table`** in this plan. It's a Phase 3+ specialist that may become a 5th tool in a `+5 tools` ablation row, but it's out of scope for the v1 table.
- **Not pursuing perfect parser-bench parity beyond ±2pp.** The benchmark itself has gold-quality issues (e.g. ambiguous-direction percentages) we noted in earlier work; agreeing with parser-bench's scorer is the bar, not exceeding it.

## Implementation Approach

Each phase below:

1. Lands as multiple small commits (per `feedback_commit_granularity`).
2. Has automated + manual success criteria.
3. Includes a "what cell does this affect" line so we know which row of the headline table this work touches.

Phases 1–3 are pure infrastructure — they don't change any number, just enable measuring more numbers cleanly. Phase 4 builds the missing methods. Phase 5 is "the run" — actually filling the table. Phase 6 is the OPEN-ENDED iteration that makes Our harness win in cells where it currently doesn't.

---

## Phase 1: Domain split + bootstrap CIs

### Overview

Re-aggregate the existing n=148 results bucketed by `example.domain` and add bootstrap CIs. No model re-runs. After this phase we already have **partial headline-table cells** — 2 rows (Base VLM ≈ simple/full_doc, Our harness ≈ focus/focus_default) × 2 tasks × 2 metrics = 8 cells filled, just from re-aggregating cached predictions.

**Cells affected:** Base VLM (Datasheets / Finance) × (accuracy / $/correct), Our harness +4 tools (Datasheets / Finance) × (accuracy / $/correct).

### Changes Required

#### 1. Per-domain aggregation in `eval/metrics.py`

**File**: `src/focusparse/eval/metrics.py`
**Changes**: Add `aggregate_by_domain(per_example: list[dict]) -> dict[str, AggregateMetrics]` that buckets records by `record["domain"]` (or pulls from the example via the harness) and returns one `AggregateMetrics` per domain plus an `_overall` key.

```python
def aggregate_by_domain(per_example: list[dict[str, Any]]) -> dict[str, AggregateMetrics]:
    """Same as aggregate(), but returns one AggregateMetrics per domain stem.

    Domain stems: 'datasheet', 'finance' (lowercased; '?' for unknown).
    Always includes '_overall' as the union.
    """
    buckets: dict[str, list[dict]] = {"_overall": list(per_example)}
    for r in per_example:
        d = (r.get("domain") or "?").split(".")[-1].lower()
        buckets.setdefault(d, []).append(r)
    return {key: aggregate(rows) for key, rows in buckets.items()}
```

Threading through:

- `_score_and_record` already records `example.id`; add `record["domain"] = str(example.domain)` at the same time.
- `run_simple_eval` / `run_focus_eval` call `aggregate_by_domain` and put the result in `manifest["aggregate_by_domain"]`.

#### 2. Bootstrap CIs in `eval/metrics.py`

**File**: `src/focusparse/eval/metrics.py`

```python
def bootstrap_ci(values: list[float], n_resamples: int = 1000, seed: int = 42) -> tuple[float, float]:
    """95% percentile bootstrap CI. Returns (lower, upper)."""
    import random
    if len(values) < 2:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_resamples)]
    hi = means[int(0.975 * n_resamples)]
    return (lo, hi)
```

Add `accuracy_ci` and `cost_per_correct_ci` to `AggregateMetrics`. Default seed=42 for reproducibility.

#### 3. Re-aggregate the existing n=148 results

Run the rescore-and-re-aggregate path on the cached predictions in `results/hf/full-eval-v1/` so we get the per-domain numbers without burning more API credit. Extend `scripts/rescore_predictions.py` with a `--by-domain` flag that calls `aggregate_by_domain` and prints the bucketed table.

#### 4. Tests

**File**: `tests/test_metrics.py` (new)

- `aggregate_by_domain` with a fixture of mixed-domain records: bucket counts match.
- `bootstrap_ci` with deterministic values: result reproducible across two calls (seeded).
- `bootstrap_ci` with N=1: returns (0.0, 0.0) gracefully (no bootstrap to do).

### Success Criteria

#### Automated Verification:

- [ ] `uv run pytest tests/test_metrics.py -v` passes the new cases.
- [ ] `uv run pytest` full suite stays green.
- [ ] `uv run python scripts/rescore_predictions.py --by-domain results/hf/full-eval-v1/` prints a per-domain table for `simple/full_doc` and `focus/focus_default` with CIs.

#### Manual Verification:

- [ ] Per-domain numbers look sensible: datasheet accuracy is expected to be slightly higher than overall (since they're mostly clean values + labels); finance is mostly chart-reading (harder).
- [ ] CI widths on n=47 finance cells are wide (~±10pp) but bounded.

**Cells filled after Phase 1:** 8 / 28 in the headline (Base VLM and Our harness +4 tools, both domains, both metrics).

---

## Phase 2: `+2 tools` / `+4 tools` axis

### Overview

Wire a single CLI flag `--tool-set ∈ {minimal, full}` through `run_hf_eval.py` → harness → workflow → tools. `minimal` exposes `inspect_region` + `get_text_layer`; `full` adds `expand_context` + `run_python`. The flag affects which tools are _actually called_ by each method, not just which are registered.

This is mostly plumbing for a clean ablation. No accuracy change for Our harness +4 tools (which is what `focus_default` already is); creates the +2 tools variant as a discrete row.

**Cells affected:** new "Our harness +2 tools" row in the headline (Datasheets / Finance × accuracy / $/correct = 4 cells).

### Changes Required

#### 1. `--tool-set` flag

**File**: `scripts/run_hf_eval.py`

```python
parser.add_argument(
    "--tool-set",
    choices=["minimal", "full"],
    default="full",
    help=(
        "Tool belt available to tool-using methods. minimal = inspect_region + "
        "get_text_layer; full = + expand_context + run_python. Forwarded to "
        "every agent type (focus / react / agent_baseline)."
    ),
)
```

#### 2. Tool-set enforcement in the workflow

**File**: `src/focusparse/pipeline/workflow.py`

Add `tool_set: Literal["minimal", "full"] = "full"` to `FocusWorkflow.__init__`. When `tool_set == "minimal"`:

- `_run_expand_context` is skipped (returns the inspector's evidence unchanged).
- Inspector's `auto_zoom` is forced off (since `run_python` is unavailable).

These are the only two FocusParse-specific tools, so removing them collapses the harness to "deterministic crop + native text + reasoner".

#### 3. Tests

**File**: `tests/test_workflow.py`

- `FocusWorkflow(tool_set="minimal")` runs end-to-end: trace shows no `expand_context` step and no `run_python:zoom2x` provenance.
- `FocusWorkflow(tool_set="full")` matches existing default behavior (regression).

### Success Criteria

#### Automated Verification:

- [ ] `uv run pytest tests/test_workflow.py -v` passes both variants.
- [ ] `uv run python scripts/run_hf_eval.py --agent focus --tool-set minimal --limit 5 ...` completes; the per-example trace has no expand_context step.

#### Manual Verification:

- [ ] Smoke at `--tool-set minimal --limit 7` on the Arm doc finishes with sensible accuracy (expected: 5–10pp lower than `full` since the model loses access to `run_python` zoom and graph expansion).

**Cells filled after Phase 2:** +4 cells (Our harness +2 tools row).

---

## Phase 3: `agentic_multi_page` protocol (b+c hybrid)

### Overview

Define the protocol the headline table is measured at. Each example produces:

- **Summary view** (input b): a tiled image where the tile size varies per-example (2up / 4up / 8up sampled with weights `[0.25, 0.5, 0.25]` — middle-heavy because 4up is the most realistic middle ground). The chosen tile size is recorded in the per-example record so we can split the headline by tile-size if needed.
- **Page list** (input c): the full list of staged pages for the doc, plus PDF path so tools can render arbitrary pages on demand.

Method-specific input handling:

- **Base VLM**: receives summary view only. No tools, no page list.
- **ReAct / Agent baseline / Our harness**: receive summary view (as the initial input) AND tool access to `inspect_region` / `get_text_layer`, which can address arbitrary pages from the page list.

This honors the user's b+c choice: methods see the multi-page summary (b) AND can drill into the full doc (c).

**Cells affected:** all 28 headline cells use this protocol.

### Changes Required

#### 1. Protocol implementation

**File**: `src/focusparse/eval/tile.py`

Extend `prepare_tiled_images` (already exists for tiled_2/4/8up) with a `prepare_agentic_multi_page(example, ...)` that returns:

```python
@dataclass
class AgenticMultiPageInput:
    summary_view_path: Path           # composed PNG, mixed tile size
    summary_tile_size: int            # 2, 4, or 8 — recorded for analysis
    page_list: list[Path]             # all staged page PNGs in source-page order
    pdf_path: Path | None             # for tool-driven on-demand render
```

Tile size sampled from `[2, 4, 8]` with seed `sha256(example.id)[:8]` for reproducibility. Composed via existing `make_contact_sheet`.

#### 2. Harness wiring

**File**: `src/focusparse/eval/harness.py`

`_prepare_images` returns `AgenticMultiPageInput` when `protocol == "agentic_multi_page"`. Each agent's `.run()` signature accepts it and uses the components it needs:

- `SimpleBaselineAgent.run(example, [summary_view_path], image_pages=[summary_pages])` — ignores `page_list` and `pdf_path`.
- `FocusWorkflow.run(example, page_list, pdf_path=pdf_path)` — uses page_list as the "all images" input and ignores summary_view_path (or uses it as the planner's quick-glance).
- `ReActAgent.run(example, page_list, pdf_path=pdf_path, summary_view=summary_view_path)` — same.

#### 3. Tests

**File**: `tests/test_tile.py`

- `prepare_agentic_multi_page` with a mock example: produces summary + page_list; tile size deterministic per id.
- Different example IDs → different tile sizes (sanity check the seed varies).

**File**: `tests/test_harness.py`

- `run_simple_eval(protocol="agentic_multi_page")` runs end-to-end with a mock 5-example fixture.

### Success Criteria

#### Automated Verification:

- [ ] `uv run pytest tests/test_tile.py tests/test_harness.py -v` passes.
- [ ] `uv run python scripts/run_hf_eval.py --agent simple --protocol agentic_multi_page --limit 5 ...` produces predictions where `protocol="agentic_multi_page"` and `summary_tile_size ∈ {2, 4, 8}` is recorded per example.

#### Manual Verification:

- [ ] Inspect 3 generated summary views: tile-size variety is visible; gold supporting page is one of the panes.
- [ ] Per-example record includes `summary_tile_size` so downstream analysis can split by it.

**Cells available after Phase 3:** still need methods (Phase 4). But the eval lever is in place.

---

## Phase 4: Build the missing methods (ReAct + Agent baseline) — comparator scaffolding

### Overview

Two new method types — ReAct and Agent baseline — to fill rows 2 and 3 of the headline table. Both consume the `agentic_multi_page` input. Both have `+2 tools` and `+4 tools` variants.

**This phase is comparator scaffolding, not product work.** The goal is the
**minimum viable implementation** that produces honest numbers for the headline
table. We are not optimizing these methods — we are giving them a fair shot
with the same model, the same tools, and the same protocol so that any gap
between them and Our harness is attributable to the harness architecture.

**Implementation budget:** ≤ 1 day total for both methods combined. If a
sub-task here grows beyond that, push it to a follow-up and ship the simpler
version. Comparator polish does not move the harness's cells.

**Cells affected:** 8 cells (ReAct ×2 tool sets + Agent baseline ×2 tool sets, each at 2 domains × 1 metric pair, but cost is per-cell so 8 total method×tool×task slots; each slot has 2 metrics).

### Changes Required

#### 1. ReAct loop method

**File**: `src/focusparse/pipeline/react_agent.py` (new)

A from-scratch ReAct loop using the same `ModelClient` interface as the rest of the codebase. Pseudocode:

```python
class ReActAgent:
    """LLM-driven think → act → observe loop. No FocusParse stages.

    The agent is given a tool belt and a max_iterations budget. Each iteration:
    1. LLM generates a thought + (action, action_input) JSON.
    2. Harness executes the tool with the input.
    3. Tool result becomes the next observation.
    4. LLM may emit `final_answer` to stop.

    Distinguishes from FocusWorkflow by having NO planner / router / localizer /
    inspector / expander / verifier — just the loop.
    """

    def __init__(
        self,
        *,
        backend_client: ModelClient,
        tools: list[ToolSpec],
        max_iterations: int = 8,
    ) -> None: ...

    async def run(
        self,
        example: BenchmarkExample,
        page_list: list[Path],
        *,
        pdf_path: Path | None = None,
        summary_view: Path | None = None,
    ) -> WorkflowResult: ...
```

Tool belt is a list of `ToolSpec(name, description, schema, async_fn)` so the agent's prompt can list them and the loop dispatches by name. With `tool_set=minimal`, only `inspect_region` + `get_text_layer` are passed in. With `tool_set=full`, add `expand_context` + `run_python`.

ReAct prompt template (system):

```
You are a document-parsing agent. You have access to these tools:
{tool_descriptions}

To answer the question, output JSON like:
{"thought": "...", "action": "tool_name", "action_input": {...}}

When you have enough evidence, output:
{"thought": "...", "final_answer": "...", "citations": [{"page": N, "bbox": [...]}]}
```

#### 2. Agent baseline method

**File**: `src/focusparse/pipeline/agent_baseline.py` (new)

A LangChain-style ReActAgent built on `langchain` / `langchain-openai` (added as optional dep `[agent-baselines]`). Configured with the same tool belt as the ReAct loop above.

The point of this row is **comparator hygiene**: shows that swapping in a different agent framework with the same tools doesn't reproduce FocusParse's gains, isolating "the harness architecture is the variable, not just the tool list."

If LangChain integration is heavy, fallback to LlamaIndex's `AgentRunner` (which `llama-index-workflows` already pulls in transitively).

#### 3. Wire `--agent` choices

**File**: `scripts/run_hf_eval.py`

Add `react` and `agent_baseline` to the `--agent` choices. Each accepts `--tool-set` and `--protocol agentic_multi_page`.

#### 4. Tool-belt resolver

**File**: `src/focusparse/tools/__init__.py`

```python
def resolve_tool_set(name: Literal["minimal", "full"]) -> list[ToolSpec]:
    """Return the ordered tool list for a given tool-set name."""
    base = [INSPECT_REGION_SPEC, GET_TEXT_LAYER_SPEC]
    if name == "minimal":
        return base
    return base + [EXPAND_CONTEXT_SPEC, RUN_PYTHON_SPEC]
```

Each `ToolSpec` has a Pydantic input schema, an async callable, and a name/description that goes into the agent's system prompt.

#### 5. Tests

**File**: `tests/test_react_agent.py` (new)

- Mock backend that returns a 2-step trace: (1) inspect_region call, (2) final_answer. Assert tool was actually called and answer is propagated.
- Tool-set enforcement: with `tool_set=minimal`, the agent's prompt does not list `run_python` and a fake LLM that calls `run_python` triggers a runtime error from the agent's loop (unknown tool).

**File**: `tests/test_agent_baseline.py` (new)

- Same shape: minimal mock to confirm the framework integration works.

### Success Criteria

#### Automated Verification:

- [ ] `uv run pytest tests/test_react_agent.py tests/test_agent_baseline.py -v` passes.
- [ ] `uv run python scripts/run_hf_eval.py --agent react --tool-set minimal --protocol agentic_multi_page --limit 5 ...` produces 5 predictions with `agent="react"` and trace showing tool calls.

#### Manual Verification:

- [ ] Spot-check 3 ReAct traces: the agent actually loops (≥ 2 tool calls per example on average), not just emits `final_answer` immediately.
- [ ] ReAct +4 tools accuracy is ≥ ReAct +2 tools accuracy on the smoke (sanity: more tools shouldn't hurt).

**Cells available after Phase 4:** all 7 method rows can be run; eval is just an API spend away.

---

## Phase 5: Run the headline table at n=148

### Overview

Sweep all 7 method × tool-set combinations on the full validation split at protocol `agentic_multi_page`. Total: 7 × 148 = 1036 model calls. Estimated cost $8–15 (focus and ReAct loops cost more per example than simple).

**Cells affected:** all 28 headline cells.

### Changes Required

#### 1. Headline-eval script

**File**: `scripts/run_headline_eval.py` (new)

```python
SPECS = [
    {"agent": "simple",         "tool_set": "none",    "label": "Base VLM"},
    {"agent": "react",          "tool_set": "minimal", "label": "ReAct +2 tools"},
    {"agent": "react",          "tool_set": "full",    "label": "ReAct +4 tools"},
    {"agent": "agent_baseline", "tool_set": "minimal", "label": "Agent baseline +2 tools"},
    {"agent": "agent_baseline", "tool_set": "full",    "label": "Agent baseline +4 tools"},
    {"agent": "focus",          "tool_set": "minimal", "label": "Our harness +2 tools"},
    {"agent": "focus",          "tool_set": "full",    "label": "Our harness +4 tools"},
]
```

Spawns each spec as a parallel subprocess (4-way parallelism, like the prior full-eval), aggregates by domain with CIs, writes `results/hf/headline/<ts>/headline_table.json`.

#### 2. Headline-table renderer

**File**: `scripts/render_headline_table.py` (new)

Reads `headline_table.json` and emits two outputs:

- Markdown table for the paper.
- HTML table for sanity-check viewing.

#### 3. Reproducibility appendix

**File**: `scripts/run_appendix_repro.py` (new)

Runs `simple/full_doc` with each of (GPT-5.4, Gemini 3.1 Pro, Claude 4.6) on 50-example slices and diffs against parser-bench's published numbers. Pinned ±2pp gate.

### Success Criteria

#### Automated Verification:

- [ ] `uv run python scripts/run_headline_eval.py --output-dir results/hf/headline/$(date +%Y%m%d)` completes without errors.
- [ ] `headline_table.json` has 7 method × 2 domain × 2 metric × {value, ci_lo, ci_hi} = 84 leaf entries.
- [ ] `uv run python scripts/render_headline_table.py results/hf/headline/<ts>/` produces a markdown table.
- [ ] Reproducibility appendix run shows simple/full_doc within ±2pp of parser-bench's published GPT-5.4 baseline.

#### Manual Verification:

- [ ] Headline table tells a coherent story (one row dominates, one row trails, gradient between).
- [ ] If Our harness +4 tools doesn't lead, Phase 6 has clear hill-climbing targets.
- [ ] CI widths on Finance n=47 cells are bounded (< ±15pp); if too wide, expand to dev split for Finance specifically.

**Total cells filled after Phase 5: 28 / 28.**

---

## Phase 6: Iterate on inspect + expand + tools (post-table) — **the main work**

### Overview

The headline table is the **start** of the research, not the end. Once filled, every change to FocusParse from this point forward must justify itself by **moving a specific cell** ≥ 3pp at non-overlapping CIs. Otherwise it's deprioritized.

**This is where the bulk of FocusParse engineering lives.** Phases 1–5 are
infrastructure to make this iteration measurable; the comparator methods
(Phase 4) freeze after they produce numbers. Phase 6 is open-ended and
intentionally so — every iteration here is a candidate paper figure, a
candidate ablation, or a candidate "negative result" worth recording. The
focus stays on `src/focusparse/pipeline/{localizer,inspector,expander}.py`,
`src/focusparse/tools/*`, and the trajectory recorder.

This phase **subsumes** the work in `plans/2026-04-27-phase2-sota-leverage.md` items 3–5 (verifier loop, region reranker, evidence graph) and `plans/2026-04-13-focusparse-agentic-pipeline.md` Phase 5 (multi-tier sweep). They are no longer "Phase 2 SOTA leverage" or "Phase 5 sweep" — they are **specific cell-shifters** in the headline table.

### Changes Required

For each candidate change, the workflow is:

1. **Identify the target cell**. E.g., "Our harness +4 tools / Datasheets / accuracy = 41.2%; baseline ReAct +4 tools = X. Goal: lift Our harness by ≥ 3pp."
2. **Predict the mechanism**. E.g., "Item 5 (evidence graph) should improve `cited_evidence_completeness`, which propagates to accuracy via better packets in the answer step."
3. **Implement** the change behind a feature flag (`--use-evidence-graph`).
4. **A/B at n=148** with bootstrapped CIs. Two-tailed comparison: does the change cell's CI intersect the baseline cell's CI?
5. **Decide**:
   - If non-overlapping CIs in the predicted direction: **flip the default on**, document in MEMORY.md.
   - If non-overlapping CIs in the wrong direction: **revert**, document the negative result in MEMORY.md.
   - If overlapping CIs: hold the flag opt-in; don't ship as default; either expand n or move on.

### Active candidates (in priority order — all are FocusParse harness work)

Each candidate is a focused change to one or more of the three hot stages
(`localize` / `inspect` / `expand_context`) or one of the tools. None of
them touch comparator methods.

1. **Inspector LLM-driven dispatch (sub-phase 2g step 2)** — `src/focusparse/pipeline/inspector.py`. Replace the deterministic top-N + tool-routing inspector with a ReActAgent-style loop where the inspector LLM decides _which_ regions to inspect with _which_ tool. Today the inspector picks top-N by detector score with an evidence-type boost, and routes by region*type to image/element/region modes. The smoke run on Arm shows the inspector is the weakest deterministic component (RT-DETRv2 ranks text > picture, so figure-heavy questions miss). \_Predicted cell:* `Our harness +4 tools / both domains / accuracy` — the main expected lift across the board.

2. **Item 5 — evidence-graph expansion** (`--use-evidence-graph`) — `src/focusparse/pipeline/expander.py`. The n=7 A/B under the fixed scorer showed +0.07 page*recall and +0.01 IoU. Re-run at n=148 with CIs and tune the directional / `max_distance` rules. \_Predicted cell:* `Our harness +4 tools / Datasheets / bbox_iou` and `accuracy` (datasheets carry charts + tables where the graph schema is well-defined).

3. **`expand_context` neighbor taxonomy refinement** — `src/focusparse/pipeline/evidence_graph.py`. The typed graph regressed under the broken scorer; revisit the graph rules (directional constraints, `max_distance`, `min_overlap_fraction`) with the new scorer in hand. Also: extend the graph schema for finance-specific cases (legend-binding, axis-binding, footnote-currency-unit). _Predicted cell:_ `Our harness +4 tools / Finance / bbox_iou`.

4. **Item 3 — verifier→retry loop** (`--max-retries 2`) — `src/focusparse/pipeline/workflow.py`. Default off after broken-scorer A/B. Re-evaluate under the new scorer; tune the per-action policy (`retry_localization` confidence-threshold multiplier, `expand_context` `adjacency_pad` multiplier). _Predicted cell:_ `Our harness +4 tools / Finance / accuracy` (finance charts have more "wrong-on-first-try-then-recover" cases).

5. **Auto-zoom A/B** (`--auto-zoom`) — `src/focusparse/pipeline/inspector.py:_zoom_crop`. Already shipped behind a flag. A/B at n=148 with CIs, especially on the `axis_value_interpolation` and `confusable_label` question families. _Predicted cell:_ `Our harness +4 tools / Datasheets / accuracy` on the within-row visual-reading subset.

6. **Multi-scale evidence packets** — `src/focusparse/evidence/packet.py`. Currently each packet has one `local_crop_ref`; extend to `multi_scale_crops: list[CropRef]` so the reasoner sees both a tight crop AND a wider context view. The reasoner can then reason over both scales without re-calling tools. _Predicted cell:_ `Our harness +4 tools / both domains / accuracy`. Implementation: `inspector.py` builds packets with 1 tight + 1 context-pad crop; reasoner prompt enumerates both; trajectory recorder serializes the list.

7. **`chart_to_table` specialist tool** — `src/focusparse/tools/chart_to_table.py` (currently stub). Implement gridline-peak-detection + axis-OCR fusion to extract a CSV from chart crops. Router uses it only when `question_family ∈ {axis_value_interpolation, candlestick_ohlc_extraction}`. _Predicted cell:_ `Our harness +4 tools / Finance / accuracy` (finance charts dominate this question family).

8. **Localizer-rerank prompt tuning** — `src/focusparse/pipeline/region_reranker.py`. The reranker LLM emits per-region `relevance × needed_for × missing_context`. The current prompt is generic; consider a domain-aware variant that primes for chart-vs-table-vs-text expectations. _Predicted cell:_ `Our harness +4 tools / both domains / region_precision` and `bbox_iou`.

9. **Trajectory-recorder schema bump for multi-scale + tool calls** — `src/focusparse/traces/recorder.py`. Once items 1–6 land, the trajectory schema needs a v2 to capture the richer evidence (multi-scale crops, sub-tool calls inside the inspector loop). Bump `schema_version` and document the migration in MEMORY.md.

Each candidate ends with: A/B at n=148 → bootstrapped CIs → diff-runs report → cell-by-cell entry in MEMORY.md.

### Success Criteria (per candidate)

#### Automated Verification:

- [ ] A/B at n=148 with bootstrapped CIs for both cells.
- [ ] Diff harness (`scripts/diff_runs.py`) runs and emits per-stage deltas.
- [ ] If positive: feature flag flipped to default-on; corresponding test cases updated.

#### Manual Verification:

- [ ] Negative-result candidates get a one-paragraph autopsy in MEMORY.md (what we expected, what happened, why we think it failed).
- [ ] Positive-result candidates get a "lift" entry in MEMORY.md with the cell-by-cell delta.

This phase is **open-ended**. The user signals "stop iterating, write paper" when one row of the headline table dominates with a clear mechanism story.

---

## Phase 7: Appendix experiments

### Overview

Once the headline is told, run supplementary experiments to **explain** the result. None of these is the conclusion; they're context.

### Experiments

1. **Oracle ceilings**: re-run all 7 methods at `oracle_page` and `oracle_crop` protocols. Shows how much accuracy each method _could_ have if perfect localization were free. The gap to the headline tells us where the bottleneck is (localization vs reasoning).
2. **Tile-size sweep**: re-run Our harness +4 tools at fixed `tiled_2up`, `tiled_4up`, `tiled_8up`. Shows tile-density effect on Our harness specifically.
3. **Reasoner model swap**: re-run Our harness +4 tools with reasoner ∈ {gpt-5.4, gemini-3.1-pro, claude-opus-4.6}. Shows the harness gain is model-independent.
4. **Cost-per-correct vs accuracy Pareto**: scatter plot of all 7 × 3 model variants (= 21 points) on a `(cost, accuracy)` plane, showing Our harness's Pareto frontier dominance.
5. **Failure-mode taxonomy**: for the 50% of examples Our harness gets wrong, categorize failures: visual-reading-hard / scoring-strictness / wrong-page / wrong-region / lazy-answer / abstain-when-shouldn't. Bar chart.
6. **Per-question-family breakdown**: split each headline cell by `question_family`. Shows which families each method is good/bad at.

### Success Criteria

#### Automated Verification:

- [ ] Each appendix experiment script lives under `scripts/appendix/`.
- [ ] Each produces a JSON + a markdown table.

#### Manual Verification:

- [ ] Pareto plot is publication-clean.
- [ ] Failure taxonomy is grounded in actual examples (not pure clustering).

---

## Testing Strategy

### Unit Tests

- `tests/test_metrics.py` (new): `aggregate_by_domain`, `bootstrap_ci`.
- `tests/test_react_agent.py` (new): ReAct loop with mocked LLM + tool-set enforcement.
- `tests/test_agent_baseline.py` (new): generic agent baseline integration.
- `tests/test_tile.py` (extend): `prepare_agentic_multi_page` deterministic tile-size by example id.
- `tests/test_workflow.py` (extend): `tool_set="minimal"` skips expand_context and forces auto_zoom off.

### Integration Tests

- `tests/test_headline_eval.py` (new): smoke `run_headline_eval.py --limit 3` against a mock backend; assert all 7 specs produce predictions and the merged JSON shape.

### Manual Testing Steps

1. Phase 1: `uv run python scripts/rescore_predictions.py --by-domain results/hf/full-eval-v1/` — eyeball per-domain numbers.
2. Phase 2: `uv run python scripts/run_hf_eval.py --agent focus --tool-set minimal --limit 5 ...` — check trace lacks expand_context.
3. Phase 3: smoke `agentic_multi_page` at limit 5; inspect summary view PNG and per-example record's `summary_tile_size`.
4. Phase 4: ReAct agent runs the loop for ≥ 2 iterations on at least 1 example.
5. Phase 5: full headline run completes; markdown table renders; reproducibility appendix passes ±2pp gate.

## Performance Considerations

- **Phase 5 cost**: ~1036 calls × $0.005–0.025 = $5–25 per full headline run. Use `--resume` aggressively to make iteration cheap.
- **API rate limits**: 4-way parallel is OpenAI-rate-limit-safe at gpt-5.4 (we tested in the prior full-eval run). 7-way may need rate-limit handling.
- **Tile rendering**: the `agentic_multi_page` summary view requires PDF → image rendering for noise pages. Cached per-example so reruns are cheap.
- **Bootstrap CI overhead**: 1000 resamples × 148 records = 148k operations per metric per cell. Trivial (<1s per cell).

## Migration Notes

- Existing `tiled_2/4/8up` protocols stay supported (they go to appendix tile-size sweep).
- Existing per-example records lack `domain` field (it's on the `BenchmarkExample`, just not copied). Phase 1 backfills via `aggregate_by_domain` reading `domain` from the input examples by matching `example_id`.
- `scripts/rescore_predictions.py` already in place; extend with `--by-domain` rather than write a new script.

## References

- **Prior plans this subsumes:**
  - `plans/2026-04-13-focusparse-agentic-pipeline.md` Phase 5 → Phase 7 appendix experiment 3 (model swap).
  - `plans/2026-04-27-phase2-sota-leverage.md` items 3–5 → Phase 6 candidates 1–2.
  - `plans/2026-04-27-fix-baseline-accuracy.md` → already complete; underwrites the scoring trust this plan depends on.
- **Standing context**: `.claude/memory/MEMORY.md` "Research framework" section (added concurrent with this plan).
- **Reproducibility gate**: `scripts/run_appendix_repro.py` — `simple/full_doc` GPT-5.4 must stay within ±2pp of parser-bench's published 48.6%.
- **Headline-table image** (user-provided 2026-04-29): the visual specification for the deliverable table.
