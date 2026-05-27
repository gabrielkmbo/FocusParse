---
date: 2026-05-13T16:17:34-07:00
researcher: Gabriel Bo
git_commit: 700af5f50ba73e30d83dc14e03ffedd373a5adb8
branch: harness-60plus-iteration
repository: FocusParse
topic: "Harness 60%+ accuracy iteration — kickoff handoff"
tags:
  [
    implementation,
    strategy,
    harness-iteration,
    inspect,
    expand,
    bbox,
    verifier,
    routing,
    benchmark-audit,
    accuracy-60plus,
  ]
status: complete
last_updated: 2026-05-13
last_updated_by: Gabriel Bo
type: implementation_strategy
---

# Handoff: harness-60plus iteration kickoff (target ≥60% on n=148)

## Task(s)

**Goal.** Drive FocusParse `focus_agentic_multi_page` accuracy on parser-bench
n=148 from the current **49.3% main-stack** baseline to **≥ 60%** (preferably
higher). Primary attack surface, per user direction: inspect/expand stages,
bbox/crop quality, tool orchestration (selection + sequencing), verifier
correctness, and pre-localizer page routing. Secondary attack surface, per the
benchmark-audit prompt: any failure that turns out to be a golden-answer error,
an unanswerable question, or an ambiguous spec — those get fed back into a
benchmark fix-list rather than swallowed as model errors.

**Session reset.** User is switching to a tmux VM. Nothing implementation-side
has shipped yet on this branch; this is a clean kickoff. The new session should
resume from this handoff and start with **Task #1 → draft the combined plan**.

**Tasks (TaskList, in dependency order):**

1. **[in_progress] Draft combined plan: harness-60plus iteration + benchmark audit** — write
   `plans/2026-05-13-harness-60plus-iteration.md` covering reproducer baseline,
   failure-mode triage, benchmark/golden audit, bbox+crop quality fixes,
   inspect/expand orchestration, verifier+routing iteration, and the
   iterate-to-60% loop. **This is where the next session picks up.**
2. **[pending] Reproduce main-stack baseline on n=148.** Fresh run from
   `harness-60plus-iteration` (off `main`), expect ~49.3%. Artifacts under
   `results/hf/sprint-2026-05-13/60plus-baseline-run1/`. Blocked by #1.
3. **[pending] Failure-mode triage on baseline n=148.** Bucket every wrong
   example: bad layout/bbox, wrong page routed, right region wrong reasoner
   extraction, verifier rejected a correct answer, tool not selected when it
   should have been, lazy abstention. Produce a per-example markdown/csv
   table; this dictates the iteration order. Blocked by #2.
4. **[pending] Audit benchmark goldens on failure set.** Per-failure verdict:
   `harness-error / unanswerable / golden-incorrect / ambiguous`. Output at
   `thoughts/shared/audits/2026-05-13-golden-audit.md`. Blocked by #3.
5. **[pending] Iterate inspect/expand + bbox + tool orchestration.** Code
   changes against failure buckets; A/B each on a small slice (~30 rows) first,
   then full n=148 when promising. Blocked by #3, #4.
6. **[pending] Reach 60%+ accuracy on n=148.** Final gate. Blocked by #5.

**Autonomy contract (user-confirmed).** Fully autonomous until 60%+ or blocked.
Check in only for surprising findings or genuinely destructive actions.
Cost budget: ~$100+ (enough for ~20 full n=148 runs at ~$5 each).

## Critical References

- `plans/2026-04-29-research-driven-eval-framework.md` — the active framing
  plan. The headline 4-method × 2-task × 2-metric table is the metronome; the
  new plan must declare which **cells** any change moves and how much.
- `.claude/memory/MEMORY.md` — running context, especially the **"Research
  framework"** + **"Narrowed scope"** sections at the top, the **2026-05-13
  changelog entry** (compact-normalized 30-row slice at 66.7%), and the
  **2026-05-11 afternoon entry** (81% of failures are post-localization).
- `thoughts/shared/handoffs/general/2026-05-13_15-58-07_research-presentation-and-main-stack-ab.md`
  — immediate predecessor handoff. Documents the Phase 5/6a/7 merges to main,
  the n=148 main-stack run (49.3%), variance-discipline gap, and the
  outstanding Codex WIP on `codex/harness-60-accuracy` (do not interrupt).
- `CLAUDE.md` — operational card; cells, contracts, sharp edges.

## Recent changes

No code changes on this branch yet. Setup work only:

- Created new branch `harness-60plus-iteration` off `origin/main` at commit
  `700af5f` (the research-presentation HEAD on main). Codex's parallel branch
  `codex/harness-60-accuracy` is untouched per user direction.
- Created 6 tasks in TaskList (see Task(s) section) with explicit dependency
  chain `#1 → #2 → #3 → {#4, #5} → #6`.

## Learnings

1. **Branch base decision.** User confirmed branching off `main`, **not** off
   `codex/harness-60-accuracy`. Codex has 3 commits ahead (compact-answer
   shape normalization) and reported 66.7% on a 30-row slice, but those are
   speculative and off-mainline. Cherry-pick them later if the audit shows
   value; do not branch onto codex's worktree.
2. **Baseline number to beat.** `results/hf/sprint-2026-05-13/main-stack-run1/focusparse_focus_agentic_multi_page_333fe987.json`
   → **49.3% overall** (56.7% datasheet, 40.9% finance), `page_recall=0.866`,
   `bbox_iou=0.799`, `lazy_answer_rate=0.081`, `tool_calls_mean=0.95`,
   `cost_per_correct=$0.026`, `total_cost=$1.89` for n=148. **Localization is
   strong already** — the gap to 60% is mostly post-localization (reasoner
   extraction + verifier judgment + tool-selection misses).
3. **Failure-mode prior (from 2026-05-11 afternoon MEMORY entry):** 81% of
   wrong examples have IoU≥0.3 and page_recall≥0.5 (right region, wrong
   extraction). Of those: ~16 are prompt-fixable (gold-in-pred, pred-in-gold,
   normalized-match); ~43 are genuine reasoner errors needing
   self-consistency or stronger model. This is the failure prior driving
   priority order in #5.
4. **Domain-divergent prompt finding (Phase 6a).** Global `exact_match`
   prompt tightening moved datasheets +7.3pp but finance −11.4pp. The
   cheapest next mechanism lever, per the previous handoff's "Action Items
   #2", is **per-domain prompt routing** (route the exact_match format hint
   by `question.domain` or `plan.question_family`). Predicted: recover
   finance to ~43% while keeping datasheet at ~59% → **overall ~52%**. That
   is the single highest-EV cheap change to attempt early.
5. **Variance discipline is the credibility gate.** Single-run n=148 deltas
   under ±3pp are within noise. Use `LLMResponseCache` +
   `CachingModelClient` (`src/focusparse/cache/store.py`,
   `src/focusparse/models/tiers.py`) via
   `--llm-cache-dir cache/llm_responses/<run-name> --llm-cache-mode record-or-replay`
   for any change that moves <5pp. Reasoner + verifier are **never** cached
   (they are the dependent variable); only `planner` and `localizer_rerank`
   are.
6. **Layout endpoint is on Modal now**, not HF. Default endpoint:
   `https://llamaindex--layout-v3-triton-layoutv3triton-serve.modal.run`.
   Token: `LAYOUT_EXTRACTION_V3_MODAL_TOKEN`. `HF_TOKEN` remains a legacy
   fallback only. Keep layout preflight strict so endpoint outages abort
   before reasoner calls.
7. **Hot files for iteration #5** (per CLAUDE.md and the narrowed-scope
   memory section):
   - `src/focusparse/pipeline/inspector.py` (1263 LoC) — the main
     deterministic loop + chart_to_table dispatcher.
   - `src/focusparse/pipeline/expander.py` (1537 LoC) — neighbor taxonomy +
     graph-aware attachment.
   - `src/focusparse/pipeline/localizer.py` (249 LoC) — rerank + bbox merge.
   - `src/focusparse/pipeline/verifier.py` (562 LoC) — abstain routing +
     structured-output retry.
   - `src/focusparse/pipeline/router.py` (136 LoC) — FTS5/BM25 page routing.
   - `src/focusparse/pipeline/workflow.py` (2360 LoC) — dispatch + dynamic
     gates (`_should_use_react_inspector`, `_run_expand` initial-gate).
   - `src/focusparse/tools/inspect_region.py` (432 LoC) — 3 modes
     (image/element/region); **do not add a 4th mode without plan update**.
   - `src/focusparse/tools/layout_detect.py` (308 LoC) — Modal client; must
     raise on full-page stub.
   - `src/focusparse/tools/expand_context.py` (25 LoC) — thin shim around
     the expander.
8. **Repo conventions.** Plans live at `plans/YYYY-MM-DD-name.md` (kebab).
   Audits/research go under `thoughts/shared/audits/` and
   `docs/research/`. Eval artifacts under `results/hf/sprint-2026-05-13/`.
   Trace schema is at `schema_version = "1"` — bump if any field changes.
9. **Don't introduce a 4th `inspect_region` mode.** CLAUDE.md flags this as a
   load-bearing contract — needs a plan update first. The 3 modes
   (image / element / region) are sufficient for everything in scope.
10. **Codex's WIP must not be disturbed.** Three stashes belong to Codex on
    `codex/harness-60-accuracy`. Switching branches there will require
    Codex to restore its stash; from this branch (`harness-60plus-iteration`)
    we never need to switch into codex's worktree.

## Artifacts

**Planned (next session writes these — none exist yet):**

- `plans/2026-05-13-harness-60plus-iteration.md` — the combined plan to
  produce in Task #1. Should mirror the
  `plans/2026-04-29-research-driven-eval-framework.md` structure
  (Overview / Current State / Desired End State / What We're Not Doing /
  Implementation Approach / Phase 1..N / Success Criteria). Sections:
  - Phase 0: reproduce baseline on this branch (Task #2).
  - Phase 1: failure-mode triage (Task #3).
  - Phase 2: golden audit on the failure set (Task #4) — feeds into
    `thoughts/shared/audits/2026-05-13-golden-audit.md`.
  - Phase 3a: bbox + crop quality fixes (layout neighbor merging, padding
    policy, IoU sanity in `localizer.py` + `layout_detect.py`).
  - Phase 3b: inspect/expand orchestration (per-domain prompt routing
    first, then mode-selection tuning + neighbor taxonomy in `inspector.py`,
    `expander.py`).
  - Phase 3c: verifier abstain-routing + page-router improvements
    (`verifier.py`, `router.py`).
  - Phase 4: iterate-to-60% loop with explicit A/B protocol (small slice
    first via `--llm-cache-dir`, n=148 only when slice CI is
    non-overlapping).
- `results/hf/sprint-2026-05-13/60plus-baseline-run1/focusparse_focus_agentic_multi_page_*.json`
  — Task #2 reproducer artifact.
- `thoughts/shared/audits/2026-05-13-golden-audit.md` — Task #4 per-example
  verdicts.

**Existing references the next session must read:**

- `results/hf/sprint-2026-05-13/main-stack-run1/focusparse_focus_agentic_multi_page_333fe987.json`
  — canonical 49.3% baseline; numbers above pulled from `.overall`.
- `results/hf/sprint-2026-05-13/main-stack-run1/focusparse_focus_agentic_multi_page_333fe987/`
  — `per_example.jsonl`, `predictions/`, `run.json`, `tiles/`. **Source of
  truth for failure-mode triage in #3** (don't re-run; pull from this dir).
- `plans/2026-04-29-research-driven-eval-framework.md` — the framing plan
  that the new plan should subordinate itself to, not replace.
- `.claude/memory/MEMORY.md` — running context. The 2026-05-13 entries
  (compact-normalized 30-row slice 66.7%; dynamic initial-expand gating)
  show what's already been tried and where the diminishing returns hit.
- `scripts/diagnose_predictions.py` — already exists for failure-mode
  mining; the head of file documents usage. Use this for Task #3 rather
  than writing a new diagnoser from scratch.
- `scripts/audit_parser_bench_goldens.py` — already exists for golden audit
  via HF Dataset Viewer; the head of file documents usage. Use as the
  starting point for Task #4.
- `scripts/run_hf_eval.py` — single-config runner used for the eval in #2
  and slice A/Bs in #5.

## Action Items & Next Steps

In order — the new session should pick up at #1 directly:

1. **Write the combined plan** at
   `plans/2026-05-13-harness-60plus-iteration.md`. Follow the structure in
   the Artifacts section above. Each phase must answer: which **cell** in
   the headline table does it move, by how much, and through what
   stage-level mechanism (use `bbox_iou`, `page_recall`,
   `cited_evidence_completeness`, `verifier_abstain_rate`,
   `lazy_answer_rate`). Move TaskList #1 → completed when done.
2. **Reproduce baseline.** Fresh `uv run python scripts/run_hf_eval.py
--agent focus --protocol agentic_multi_page --hf-split validation
--output-dir results/hf/sprint-2026-05-13/60plus-baseline-run1/` (check
   the exact flags in `run_hf_eval.py:1-60` — protocol is
   `agentic_multi_page`, agent is `focus`). Confirm overall accuracy lands
   in the [47.0, 51.5] band around the 49.3% main-stack number; if it
   doesn't, **stop and investigate before iterating** — that's a config
   drift or endpoint outage, not a model finding.
3. **Run failure-mode triage.** Use `scripts/diagnose_predictions.py
--spec-dir results/hf/sprint-2026-05-13/60plus-baseline-run1/` to
   produce the per-bucket counts; then for each wrong row, inspect
   `predictions/<id>.json` + `per_example.jsonl` and assign one of:
   `bad_layout / wrong_page / wrong_extraction / verifier_rejected_correct /
tool_missed / lazy_abstain`. Output a markdown table at
   `thoughts/shared/audits/2026-05-13-failure-triage.md`.
4. **Golden audit.** Run `scripts/audit_parser_bench_goldens.py` against
   the failure set IDs (NOT the whole 148 — too slow). For each
   `wrong_extraction` and `lazy_abstain`, manually compare the predicted
   answer to the golden via the source PDF/image. Verdict each as
   `harness_error / unanswerable / golden_incorrect / ambiguous`. Output
   at `thoughts/shared/audits/2026-05-13-golden-audit.md`.
5. **Iterate.** Highest-EV cheap lever first: **per-domain prompt
   routing** in `src/focusparse/pipeline/reasoner.py::_format_hint`
   (predicted: +3 to +5pp overall). Then walk down the triage table
   addressing each bucket in order of bucket size. A/B every change on a
   30-row slice using `--llm-cache-dir cache/llm_responses/<run-name>
--llm-cache-mode record-or-replay` (planner + localizer_rerank cached;
   reasoner + verifier never cached). Promote to n=148 only when slice
   delta is ≥3pp and CIs are non-overlapping.
6. **Commit cadence.** Per `feedback_commit_granularity` memory: many
   small commits, split by file/concern/phase. After every substantive
   commit, append a one-line entry to `.claude/memory/project_changelog.md`.
   Push to `origin/harness-60plus-iteration` periodically so the user can
   monitor remotely from the tmux VM.
7. **Stopping condition.** A clean n=148 run on `agentic_multi_page` at
   ≥60.0% overall accuracy with `lazy_answer_rate ≤ baseline + 1pp` and
   bbox_iou not regressing more than 2pp. When hit, mark Task #6
   completed, write the result up at
   `docs/research/2026-05-13-harness-60plus-results.md`, and stop iterating
   (further work needs new direction).

## Other Notes

- **Branch is `harness-60plus-iteration` tracking `origin/main`** (no
  upstream yet; first `git push -u origin harness-60plus-iteration` from
  the new session will publish it). Codex's `codex/harness-60-accuracy`
  branch and `path-a-iteration` worktree at `/Users/gabrielbo/projects/FocusParse-path-a-iteration`
  are unaffected.
- **Two stale untracked files** at session start that are not session
  artifacts and should be left alone: `focusparse.pptx` (user's
  presentation export) and `thoughts/shared/handoffs/general/2026-05-13_15-58-07_research-presentation-and-main-stack-ab.md`
  (the predecessor handoff — read it; do not delete).
- **Tier config is at `tier_sha8 = 333fe987`** (`configs/default.yaml`
  with `inspector_dispatch: mid`). All sprint runs land under that
  namespace; do not change tier configs as part of accuracy iteration —
  that's the model-swap appendix axis, not the harness axis. If a change
  needs a new tier config, save it as a sibling `configs/<experiment>.yaml`
  and pass via `--config-override`.
- **Mid-iteration save**: nothing in flight to lose. Branch is clean
  (only the two pre-existing untracked files noted above). No code
  changes have been made yet.
- **Cost monitoring.** ~$5/full n=148 run × ~20 runs of headroom →
  budget allows aggressive A/B. Use the slice-first protocol to keep
  per-experiment cost <$1 in 90% of cases.
- **Don't bypass the `inspect_region` 3-mode contract** or modify the
  parser-bench submodule. Both are load-bearing per CLAUDE.md.
- **Variance harness reminder**: `LLMResponseCache` + `CachingModelClient`
  are wired but not the default. The `--llm-cache-mode` modes are
  `record-or-replay` (default for A/B) vs `record-only` (initial pass).
  Reasoner + verifier intentionally bypass cache so the dependent
  variable stays live. See `src/focusparse/cache/store.py` and
  `src/focusparse/models/tiers.py`.
