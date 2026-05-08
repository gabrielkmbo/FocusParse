---
date: 2026-05-07T08:55:00-07:00
researcher: Gabriel Bo
git_commit: bad9132
branch: main
repository: FocusParse
topic: "Codex onboarding — full project context for a long coding session"
tags: [onboarding, codex, sprint-state, path-a, philosophy]
status: handoff
last_updated: 2026-05-07
last_updated_by: Gabriel Bo
type: onboarding
---

# Codex onboarding — FocusParse

Read this doc front-to-back once. Then open the files it points at. Don't
re-derive anything that's already documented in `.claude/memory/MEMORY.md`
or in the active plans — those are the source of truth.

## 1. 90-second pitch

FocusParse runs a **hierarchical, budget-aware agentic workflow** over the
`gabrielbo/parser-bench` benchmark (148-row canonical validation split,
101 datasheet + 47 finance) and emits **citation-grounded answers +
trajectory traces**. The `parser-bench` repo is a read-only git submodule
at `third_party/parser-bench/`.

The 7 pipeline stages: `plan → route_pages → localize → rerank → inspect →
expand_context → answer → verify`. Lives in `src/focusparse/pipeline/`.

The reasoner sees ONLY `EvidencePacket`s the inspector built — never raw
pages. That's the architectural claim.

## 2. The research claim (the only thing that matters)

**One headline 4-method × 2-task × 2-metric table** drives every change:

```
                          | Datasheets (n=101)     | Finance (n=47)
                          | accuracy | $/correct   | accuracy | $/correct
--------------------------|----------|-------------|----------|----------
Base VLM (no tools)       |          |             |          |
ReAct +2 / +4 tools       |          |             |          |
Agent baseline +2 / +4    |          |             |          |
Our harness +2 / +4 tools |          |             |          |
```

The causal claim: **FocusParse's evidence-localization-first agent harness
beats both base VLMs and generic ReAct agents on high-resolution
domain-specific document parsing**.

How to evaluate any proposed change (the 4-question rubric in MEMORY.md):

1. Which **cell** does it move?
2. By **how much** (specify a number, even if a guess)?
3. Through what **mechanism** (pipe through a stage-level metric)?
4. After implementation: A/B at n=148 with bootstrapped CIs. ≥3pp at
   non-overlapping CIs → ship default. Else opt-in flag, negative-result
   note in MEMORY.md, move on.

If a change can't answer 1-3 honestly, **deprioritize it**.

## 3. Where to read first (in this order)

Read these in order before touching any code:

1. **`AGENTS.md`** (this repo's operational card — commands, structure,
   contracts, failure modes). NOTE: Lines referring to `.Codex/memory/`
   are stale; real memory is at `.claude/memory/MEMORY.md` (see fix
   below).
2. **`.claude/memory/MEMORY.md`** — the running context. Standing context
   at the top, dated changelog at the bottom (newest first). The 2026-05-06
   and 2026-05-07 entries are the current state of play.
3. **`plans/2026-04-29-research-driven-eval-framework.md`** — the master
   research plan. Defines the headline table and the 4-question rubric.
   Subsumes prior plans (listed at its bottom).
4. **`plans/2026-05-04-harness-iteration-sprint.md`** — the active sprint.
   5 phases (B1 = expand_context, B2 = run_python, B3 = inspector ranker,
   chart_to_table, multi-scale packets). Phases 1-3 + B1.5 shipped.
5. **`plans/2026-05-06-path-a-plumb-neighbors-into-reasoner.md`** —
   Path A plan. Path A's three commits **shipped this morning** (commits
   `44c956e` `fb1b237` `bad9132`); the n=148 A/B is pending.

## 4. Codebase landmarks

```
FocusParse/
├── configs/default.yaml              # tier mapping + endpoints + dataset pin
├── plans/                            # design docs; newest plan is active
├── scripts/                          # CLI entrypoints
│   ├── run_hf_eval.py                #   single-spec eval runner
│   ├── run_headline_eval.py          #   7-spec orchestrator
│   ├── render_headline_table.py      #   md/html renderer
│   ├── compare_headline_tables.py    #   cell-by-cell delta with gate markers
│   └── diagnose_predictions.py       #   failure-mode mining
├── src/focusparse/
│   ├── cli/                          # `focus` typer app
│   ├── pipeline/                     # @step modules, 1:1 with stage machine
│   │   ├── workflow.py               #   FocusWorkflow + SimpleBaselineAgent
│   │   ├── events.py                 #   typed events (no dict payloads)
│   │   ├── planner.py                #   cheap-tier LLM
│   │   ├── router.py                 #   FTS5 + BM25
│   │   ├── localizer.py              #   HF RT-DETRv2
│   │   ├── region_reranker.py        #   mid-tier LLM, populates relevance + needed_for
│   │   ├── inspector.py              #   smart-deterministic + auto_zoom + chart_to_table
│   │   ├── inspector_react.py        #   LLM-driven inspector (sprint Phase 1)
│   │   ├── expander.py               #   neighbor attachment (B1+B1.5 query-aware)
│   │   ├── reasoner.py               #   Path A surfaces neighbors as images
│   │   └── verifier.py               #   mid-tier LLM, retry-loop controller
│   ├── tools/                        # FunctionTool primitives
│   │   ├── inspect_region.py         #   image | element | region modes
│   │   ├── run_python.py             #   sandboxed coding-zoom
│   │   ├── layout_detect.py          #   HF endpoint client
│   │   ├── chart_to_table.py         #   gridline + axis OCR fusion
│   │   └── get_text_layer.py         #   PyMuPDF text extraction
│   ├── evidence/packet.py            # EvidencePacket — load-bearing contract
│   ├── eval/                         # harness + scoring + metrics + reports
│   ├── traces/                       # recorder + export (SCHEMA_VERSION="3" today)
│   ├── retrieval/text_index.py       # sqlite FTS5
│   └── dataset/loader.py             # HF streaming + local JSONL
├── tests/                            # pytest, ~600+ tests
├── third_party/parser-bench/         # git submodule, READ-ONLY
├── .claude/memory/MEMORY.md          # ← THE running context (read this first)
├── AGENTS.md                         # operational card (this is for you, Codex)
├── CLAUDE.md                         # parallel operational card for Claude
└── pyproject.toml                    # uv-managed, py ≥ 3.11, ruff line-length 100
```

### Load-bearing contracts (don't break silently)

- `src/focusparse/evidence/packet.py::EvidencePacket` — every reasoner call
  receives `list[EvidencePacket]`, never raw pages.
- `src/focusparse/eval/scoring.py::score_evidence_reward` — lazy-answer
  penalty applies when a prediction has citations but the predicted bbox
  covers >60% of the page.
- `src/focusparse/traces/export.py::SCHEMA_VERSION` — currently `"3"`.
  Bump on any field change + log migration in `.claude/memory/MEMORY.md`.
- `src/focusparse/tools/inspect_region.py` — exactly 3 modes (image /
  element / region). A 4th mode needs a plan update.
- `third_party/parser-bench/` — submodule, read-only.

## 5. Today's state (2026-05-07 morning)

### What's measured

The canonical baseline is **`results/hf/headline-v1-rebaseline-v2/`** (7
specs × n=148, all on the pinned HF revision `3774c67`):

| Method             | Datasheets | Finance  | Overall  | $/correct |
| ------------------ | ---------- | -------- | -------- | --------- |
| Base VLM           | 40.6%      | 31.9%    | 37.8%    | $0.011    |
| ReAct +2           | 16.8       | 6.4      | 13.5     | $0.18     |
| ReAct +4           | 18.8       | 4.3      | 14.2     | $0.27     |
| Agent baseline +2  | 9.9        | 4.3      | 8.1      | $0.13     |
| Agent baseline +4  | 7.9        | 4.3      | 6.8      | $0.16     |
| **Our harness +2** | **56.4**   | **36.2** | **50.0** | $0.015    |
| Our harness +4     | 49.5       | 31.9     | 43.9     | $0.018    |

**Headline finding**: Our harness +2 leads Base VLM by +12.2pp Overall.
But CIs touch at the boundary (Our harness +2 lower bound 42.6 vs
Base VLM upper bound 46.6) — directional win, not yet statistically
separable at 95% bootstrap.

### The +2 vs +4 inversion (and what we learned)

**Counter-intuitive result**: Our harness +2 (50.0%) beats +4 (43.9%) by
6.1pp. The only behavioral difference between +2 and +4 is whether
`expand_context` runs (+4) or skips (+2).

**Key diagnosis** (2026-05-06 entry in MEMORY.md):

1. `expand_context` populated `linked_crop_refs` on every packet but
   `pipeline/reasoner.py` **never read them** — neighbor crops reached
   the trace viewer + SFT export but never the model.
2. The +2 vs +4 packet sets are **different in 97% of examples**, not
   because of expand_context but because of **upstream LLM stochasticity**
   (planner=gemini, router=gemini, reranker=claude-haiku, all non-zero
   temp). Two near-identical-code runs of focus +4 produced packet sets
   that differed in 97% of examples.
3. Run-to-run variance floor on focus +4 across last evening's three runs
   spans 43.9% → 45.3% → 50.7% (~7pp). **Bigger than most predicted lifts
   in the sprint plan.**

**Implication**: Single-run A/Bs at n=148 cannot reliably measure
inspect/expand-stage changes. Decisions need either (a) ≥2 averaged runs,
(b) cached upstream outputs (deterministic upstream, swap only the stage
under test), or (c) lower upstream temperature (risk: planner emergent
behavior may depend on sampling).

### What just shipped (today, 2026-05-07)

**Path A — plumb expand_context neighbors into the reasoner.** Three
commits, all green:

- `44c956e` Path A 1/3: `_collect_packet_images` walks `linked_crop_refs`
  after the primary crop. Pre-Path-A this was dead code.
- `fb1b237` Path A 2/3: `_render_packet_line` lists
  `"Attached neighbors (N): caption, footnote, ..."` so the reasoner
  knows which images that follow are context vs primary.
- `bad9132` Path A 3/3: `_SYSTEM_PROMPT` explains the layout: "primary
  crop to ground the answer; consult neighbors only when surrounding
  text matters."

19 reasoner tests green. 81 reasoner + workflow + focus_harness tests
green. Ruff clean.

## 6. What's next

### Immediate: validate Path A

Run the A/B at n=148 (+plan caveat: ≥2 runs averaged):

```bash
set -a && source .env && set +a && \
uv run python scripts/run_hf_eval.py \
  --agent focus --tool-set full \
  --protocol agentic_multi_page \
  --output-dir results/hf/sprint-2026-05-06/path-a-run1 \
  --staging-dir ~/.cache/focusparse/hf_staging \
  --pdfs-root ~/.cache/focusparse/pdfs \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb
```

Repeat with `--output-dir .../path-a-run2`. Average accuracies. ~$2-3 each.

Compare against rebaseline-v2 focus +4 (43.9% Overall) using
`scripts/compare_headline_tables.py`. Decision rule (per the plan):

| Result (averaged) | Action                                                                                    |
| ----------------- | ----------------------------------------------------------------------------------------- |
| ≥+3pp non-overlap | Ship Path A default-on. expand_context is now load-bearing.                               |
| 0 to +3pp         | Ship as opt-in flag, document per-family wins.                                            |
| Within ±2pp       | Treat as noise. Pivot to **Path B**: text-summary attachment instead of image attachment. |
| Regression        | Revert Path A's plumbing. Image attachment confirms "more images = dilution."             |

### After Path A: pick the next sprint phase

Phase 6 candidates remaining (priority-ordered, all in
`plans/2026-05-04-harness-iteration-sprint.md`):

1. **Inspector LLM-driven dispatch** — `inspector_react.py` already wired
   behind `--react-inspector`. Pending A/B.
2. **Multi-scale evidence packets** — `multi_scale_packets=True` flag.
   Pending A/B. WARNING: multi-scale doubles images per packet; data has
   suggested "more images = more dilution" before. Run only after Path A
   tells us whether image-attachment helps at all.
3. **chart_to_table** — `chart_to_table_enabled=True` flag, gated on
   `question_family ∈ {axis_value_interpolation, candlestick_ohlc_extraction}`
   AND `figure_class ∈ {bar_chart, line_chart, candlestick}`. Finance-
   targeted. Pending A/B.

### Variance harness (load-bearing for credibility)

Tomorrow's bigger architectural improvement: build a **deterministic
upstream cache** so per-stage A/Bs aren't dominated by upstream LLM
sampling noise. The pattern: cache (planner, router, reranker) outputs
keyed by `(example_id, code_sha)`; replay cached outputs when the only
change is in `inspector / expander / reasoner`. Without this, the
sprint's headline lift claims are noise-floor-bounded.

## 7. What NOT to touch

- **`parser-bench`** submodule. Propose changes upstream in separate PRs.
- **Comparator methods** (`react_agent.py`, `agent_baseline.py`). Per the
  active plan: comparators are scaffolding; FocusParse harness is the
  product. Don't optimize them.
- **`plan / route_pages / answer / verify` stages**. Frozen per
  MEMORY.md "Narrowed scope" table. Optimization effort goes to
  `localize / inspect / expand_context` and `tools/*`.
- **`.env`**. Gitignored. Source it before runs (`set -a && source .env && set +a`).
- **`results/`** and **`cache/`**. Gitignored. Wipe-and-rerun is fine.

## 8. Conventions

### Commits

- **One concern per commit**, granular. See
  `.claude/projects/-Users-gabrielbo-projects-FocusParse/memory/feedback_commit_granularity.md`.
- Commit messages: action-first, ~50 char subject. Body explains the
  WHY (mechanism, motivating data) more than the WHAT.
- Never commit `.env`, never `--no-verify`, never force-push.

### Tests

- pytest. ~600+ tests across `tests/`.
- New modules land with their own test file; new branches in existing
  modules extend the matching test file.
- `parser_bench_submodule_present` fixture skips tests requiring the
  benchmark schema. Mock backends (`_FakeClient`, `_ScriptedClient`) for
  LLM-touching tests.

### Ruff

- Line-length 100 (`pyproject.toml`).
- `uv run ruff check src/ tests/ scripts/` before commit.
- `uv run ruff format --check ...` separately.
- Two pre-existing SIM errors in `tools/run_python.py` (lines 277, 326, 342) are nested-try patterns that would change semantics if combined.
  Not from this sprint's work.

### Memory

- Append a dated entry to `.claude/memory/MEMORY.md` after any substantive
  commit (new pipeline stage, new tool, new env var, new HF endpoint,
  trajectory schema bump, new failure mode). Skip typos.
- Newest entry on top, format `## YYYY-MM-DD — topic`.
- For per-phase A/B results: 4-question rubric (cell / lift / mechanism /
  CIs).

## 9. Failure modes (from `AGENTS.md`)

| Symptom                            | Likely cause                                                       |
| ---------------------------------- | ------------------------------------------------------------------ |
| Whole-page crops only              | Layout endpoint stub fallback. Check `HF_TOKEN` + endpoint health. |
| `Generated 0 candidate examples`   | Dataset loader mismatch — bump submodule SHA.                      |
| Empty visible response from Gemini | `thinking_budget < 1024`. Set to ≥1024.                            |
| GPT-5.x "max_tokens not supported" | Use `max_completion_tokens` (different param name).                |
| Multi-turn agent reports 0 tokens  | Token usage not propagated from `TokenCountingHandler`.            |

## 10. Codex-specific note: the `AGENTS.md` pointer

`AGENTS.md` line 3 references `.Codex/memory/MEMORY.md` — that path
**does not exist** in this repo. Real memory is `.claude/memory/MEMORY.md`.
A small fix-up commit will land alongside this onboarding doc to point
`AGENTS.md` at the correct path.

## 11. The mental model in one sentence

**The headline table is the metronome.** Every commit either moves a cell
or it shouldn't have happened. Single-run cell movements at n=148 are
noisy (±7pp on focus +4 across runs); decisions live with averaged runs.
Tools are useful when their output reaches the reasoner — Path A's just-
shipped fix made expand_context's neighbors actually visible to the model
for the first time. The next ~2 weeks of work: validate Path A, then
sequence the remaining Phase 6 candidates with the variance harness in
mind.

---

**Last commit before this onboarding**: `bad9132` (Path A 3/3).

**Open the active sprint plan first**:
`plans/2026-05-04-harness-iteration-sprint.md`.
