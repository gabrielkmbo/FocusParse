---
date: 2026-05-13T15:58:07-07:00
researcher: Gabriel Bo
git_commit: 700af5f
branch: main
repository: FocusParse
topic: "Research presentation + harness-growth main-stack A/B"
tags:
  [
    research-presentation,
    harness-growth-sprint,
    phase-merges,
    main-stack-ab,
    evidence-localization,
  ]
status: complete
last_updated: 2026-05-13
last_updated_by: Gabriel Bo
type: implementation_strategy
---

# Handoff: Research presentation + main-stack harness A/B

## Task(s)

This session covered four interleaved tasks, all completed:

1. **Build a research-presentation-quality writeup** of the FocusParse vs
   generic-agents comparison. Status: **complete**. Doc at
   `docs/research/2026-05-13-research-presentation.md`, 17 slides + artifact
   paths section. Thesis: agent architecture (not raw VLM, not tool count) is
   the load-bearing axis of doc-QA accuracy and cost-efficiency. Independent
   variable: agent type (Base VLM / ReAct / Agent baseline / FocusParse).
2. **Add Background + Project-Tie-In section** to the presentation
   (Slides 3 + 4). Status: **complete**. Covers AgenticOCR, DocLens,
   Gemini 3 Agentic Vision as direct inspirations; tabulates adjacent
   benchmarks (FinMME, ChartQAPro, PlotQA, DocVQA, PDFVQA, SlideVQA,
   OmniDocBench, olmOCR, FinChart-Bench, FinRAGBench-V, DocLayNet, M6Doc,
   dots.ocr, Qwen3-VL-4B, DePlot, ChartOCR); explicit
   borrow-vs-divergence accounting per prior work.
3. **Merge harness-growth Phases 5 / 6a / 7 from their branches to main**.
   Status: **complete**. Three `--no-ff` merges on `main`; 846 tests pass
   (1 pre-existing skip); 14 lint errors are pre-existing in unrelated
   files (CLI, `scripts/rescore_predictions.py`), not from this sprint.
4. **Fire main-stack n=148 A/B** (all phases on, fresh run from merged
   main). Status: **complete**. Result: 49.3% overall, +5.4pp vs
   rebaseline-v2; +1.3pp vs Phase 4 alone (within noise). Slide 15 of the
   presentation updated with the stack row.

## Critical References

- `docs/research/2026-05-13-research-presentation.md` — the deliverable
  research presentation. Slides 3 + 4 contain the background + how
  FocusParse differs from AgenticOCR / DocLens / Gemini Agentic Vision.
  Slide 15 is the within-harness ablation table including the main-stack
  row.
- `docs/research/2026-05-11-recalibration-and-research-state.md` — the
  prior recalibration that motivated this sprint (§3 quant, §4 qual, §5
  growth signals).
- `.claude/memory/MEMORY.md` — the 2026-05-11 entries (morning + afternoon
  - Phase 5 trigger tightening + 81% post-localization finding) document
    the per-phase decisions and mechanism numbers.
- `~/.claude/plans/clever-sparking-babbage.md` — the original sprint plan
  (Phase 0-4) the merges executed against.

## Recent changes

Commits landing on `main` during this session (newest first):

- `700af5f` `docs/research/2026-05-13-research-presentation.md:529-585` —
  appended main-stack ablation row to Slide 15 with mechanism check
  (dispatcher 7/148 4.7%; `chart_csv` populated 97/148 = 66%); reframed
  Phase 6a as a "domain-divergent" finding pointing at per-domain prompt
  routing as the next experiment.
- `bb020d8` `docs/research/2026-05-13-research-presentation.md:57-225` —
  inserted Slides 3 (Background) and 4 (Project Tie-In); renumbered
  subsequent slides 3-15 → 5-17.
- `1642f95` `docs/research/2026-05-13-research-presentation.md` (new) —
  initial research presentation with 15 slides.
- `65dd064` Merge Phase 7 — `chart_to_table_llm` in
  `src/focusparse/tools/chart_to_table.py:119-218`; new
  `chart_to_table_backend` plumbing in
  `src/focusparse/pipeline/inspector.py:321` and
  `src/focusparse/pipeline/inspector_react.py:126`;
  `src/focusparse/pipeline/workflow.py:1042-1058` wires
  `self._client_for("localizer_rerank")` as the chart backend on both
  deterministic and ReAct paths. 18 chart_to_table tests in
  `tests/test_chart_to_table.py`.
- `4ff2b08` Merge Phase 6a — exact_match format hint expanded with 4
  concrete rules at `src/focusparse/pipeline/reasoner.py:97-136`. New
  regression test `tests/test_reasoner.py:441-458`.
- `6e01698` Merge Phase 5 — `_should_use_react_inspector` tightened from
  OR to AND at `src/focusparse/pipeline/workflow.py:91-128`. 5 new unit
  tests + 1 behavior test in `tests/test_workflow.py`.

Local changes still uncommitted on `codex/harness-60-accuracy` (Codex's
parallel work, NOT included in main): stashed under
`stash@{0}: On main: codex-temp-false-abstention-retry` and
`stash@{1}: On codex/harness-60-accuracy: codex-harness-60-accuracy WIP
on reasoner.py + test_reasoner.py` and
`stash@{2}: On codex/harness-60-accuracy: codex WIP 2: reasoner+workflow+tests`.

## Learnings

1. **Variance floor is the actual bottleneck for sprint decisions.**
   Single-run n=148 deltas under ±3pp are within noise. The Phase 5
   result (-2.7pp from P4) and Phase 6a result (+0.6pp overall) both
   landed inside the floor. Multi-replicate or variance-harness runs
   are the only way to claim small wins.
2. **Phase 6a's exact_match prompt tightening is domain-divergent.**
   Datasheets +7.3pp (52.5% → 59.8%); finance -11.4pp (43.2% → 31.8%).
   The stack partially recovers finance when Phase 7's `chart_csv` is
   layered in (40.9% on stack vs 31.8% Phase 6a alone). **Per-domain
   prompt routing is the cleanest next lever**, not another universal
   prompt tweak.
3. **Phase 7 (chart_to_table LLM swap) is mechanism-decisive.** `chart_csv`
   populated went from 0/148 (OCR pipeline) → 97/148 = 66% (LLM swap).
   The accuracy lift is modest (~+1pp) because chart extraction matters
   on ~30 finance examples where the reasoner can't visually read the
   chart; on those examples CSV grounding is the difference between
   right and "Unanswerable".
4. **Phase 4 slice analysis showed react_hard_case dispatcher was
   net-negative on its slice (-3.9pp on the 51-example slice it fired
   on).** Phase 4's +4.1pp overall came entirely from the deterministic
   slice. Phase 5's AND-gating cut the dispatcher firing rate from 35%
   → 5% but didn't conclusively improve accuracy. The full mechanism is
   documented in `.claude/memory/MEMORY.md` 2026-05-11 afternoon entry.
5. **81% of harness failures are post-localization.** 62 of 77 wrong
   examples in Phase 4 have IoU≥0.3 and page_recall≥0.5 — right region,
   wrong extraction. Within those 62: ~16 are prompt-fixable (gold-in-pred,
   pred-in-gold, normalized-match); ~43 are genuine reasoner errors
   needing self-consistency or a stronger model. This was the diagnostic
   that motivated Phase 6a and Phase 6b.
6. **`run_hf_eval.py` works with `--skip-layout-preflight`** when the
   layout endpoint is paused (which it was at one point). The 282
   cached layout responses in `cache/layout/` cover most of the n=148
   examples; cache misses fall back to skeleton regions (visible as
   "whole page crops" in traces).
7. **Cherry-picking docs across branches works fine.** Each time the
   working tree switched to `codex/harness-60-accuracy`, I had to
   stash Codex's WIP, switch to main, cherry-pick my doc commit, then
   leave the stash for Codex to restore.

## Artifacts

- **Research presentation (deliverable)**:
  `docs/research/2026-05-13-research-presentation.md` — 17 slides
- **Phase 4 baseline**:
  `results/hf/sprint-2026-05-11/phase4-run1/focusparse_focus_agentic_multi_page_333fe987.json`
  (48.0% overall, n=148)
- **Phase 5 result**:
  `results/hf/sprint-2026-05-11/phase5-run1/focusparse_focus_agentic_multi_page_333fe987.json`
  (45.3% overall, dispatcher fires 4.7%)
- **Phase 6a result**:
  `results/hf/sprint-2026-05-11/phase6a-run1/focusparse_focus_agentic_multi_page_333fe987.json`
  (48.6% overall, datasheet 59.8%, finance 31.8%)
- **Main-stack result (new this session)**:
  `results/hf/sprint-2026-05-13/main-stack-run1/focusparse_focus_agentic_multi_page_333fe987.json`
  (49.3% overall, 56.7% datasheet, 40.9% finance, `chart_csv` populated
  97/148 = 66%)
- **Rebaseline-v2 (canonical 7-row table)**:
  `results/hf/headline-v1-rebaseline-v2/headline_table.{md,html,json}`
- **Recalibration doc**:
  `docs/research/2026-05-11-recalibration-and-research-state.md`
- **Memory**: `.claude/memory/MEMORY.md` 2026-05-11 morning, afternoon,
  and 2026-05-06 (Path A) entries
- **Sprint plan**: `~/.claude/plans/clever-sparking-babbage.md`
- **Integration-run template (companion)**:
  `docs/research/2026-05-12-integration-run-results.md`

## Action Items & Next Steps

In priority order for the next agent picking this up:

1. **Address the variance discipline gap.** All within-harness deltas
   are single-run; the +5.4pp main-stack vs rebaseline-v2 number is
   directional. The Phase 0 variance harness (`LLMResponseCache` +
   `CachingModelClient`) was shipped but never used for sprint A/Bs.
   Run main-stack twice more under the variance cache; report mean +
   std. ~$5 total. This is the single biggest credibility lift before
   any paper-quality presentation.
2. **Per-domain prompt routing** is the cleanest next mechanism lever.
   Phase 6a's domain-divergent result says the global exact_match
   prompt is over-tuned for datasheets and hurts finance. Route the
   prompt variant by `question.domain` (or `plan.question_family`)
   instead of one global prompt. Predicted: recover finance to ~43%
   while keeping datasheet at ~59% → overall ~52%. Cheap to implement
   (small change in `reasoner._format_hint`); A/B at n=148 ~$2.
3. **Phase 6b — reasoner self-consistency** for the 43 "right region,
   wrong value" failures. K=2 sampling with a second prompt variant,
   pick the more concise / higher-confidence answer. Doubles reasoner
   cost (~+$1.50/run) but targets the largest failure bucket. Code is
   sketched in MEMORY.md; not yet implemented.
4. **Codex's `codex/harness-60-accuracy` branch** has parallel work on
   reasoner answer-shape repair (`reasoner: repair answer-shape
failures` and downstream commits — see `git log codex/harness-60-accuracy`).
   Codex left WIP in three stashes. Review whether to merge or
   integrate; check with the user before touching.
5. **Push to remote**: `git push origin main` (10 commits ahead). All
   merges + presentation are on local main but not pushed. The user
   ran `git push` in the bash command but the output showed "Everything
   up-to-date" — that may have been from a different branch context.
   Verify with `git log --oneline origin/main..main` after switching to main.
6. **Optional polish on the presentation**: convert to slidev/marp/keynote;
   add real Pareto-frontier chart images (currently ASCII). The Slide 4
   "Pareto frontier on cost × accuracy" ASCII diagram could be a real
   matplotlib scatter once the data is plotted.

## Other Notes

- **The user's research project name** is "Localized Parsing of Complex
  Documents" — that's framed as the broader research direction in
  Slide 3. FocusParse is the agentic-pipeline arm; downstream is a
  planned Qwen3-VL-4B SFT + GRPO distillation pass (not in this sprint).
- **`tier_sha8` for the merged main is `333fe987`** (up from `7d4b816d`
  on rebaseline-v2). The change is from adding `inspector_dispatch: mid`
  in `configs/default.yaml` during the Phase 2 follow-up commit
  (`d7df405`). All sprint runs land under the new namespace.
- **Codex's WIP on the `codex/harness-60-accuracy` branch** touches
  `src/focusparse/pipeline/reasoner.py`, `src/focusparse/pipeline/workflow.py`,
  `tests/test_reasoner.py`, and `tests/test_workflow.py`. Most recent
  Codex commits there: `faf6746 reasoner: compact exact answer shapes`,
  `395e08c reasoner: normalize compact exact answers`,
  `d7dad1c reasoner: document fixed-slice accuracy checkpoint`. The
  full Codex commit log is on that branch.
- **The variance-harness cache** is configured but not used by default.
  Pass `--llm-cache-dir cache/llm_responses/<run-name> --llm-cache-mode
record-or-replay` to `scripts/run_hf_eval.py` to enable. Reasoner +
  verifier are NEVER cached (they're the dependent variable); only
  `planner` and `localizer_rerank` are. See
  `src/focusparse/cache/store.py::LLMResponseCache` and
  `src/focusparse/models/tiers.py::CachingModelClient`.
- **Three pre-existing `untracked` files** are on `main` but were never
  committed: `docs/research/2026-05-11-parser-bench-golden-audit.md`,
  `docs/research/2026-05-12-scientific-recalibration-and-experiment-plan.md`,
  `scripts/audit_parser_bench_goldens.py`. These appeared in the
  presentation commit (`1642f95`); they were Codex artifacts from
  earlier sessions.
- **Three pending tasks** in the TodoList (`#63`-`#65`) cover the
  per-phase A/Bs we just completed. Mark them completed if the next
  session wants a clean task list. The mechanism work they describe is
  done.
