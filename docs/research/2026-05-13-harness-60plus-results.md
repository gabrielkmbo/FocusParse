# Harness 60%+ Iteration — Sprint Results

**Goal**: lift `focus_agentic_multi_page` accuracy on parser-bench n=148
from the 49.3% main-stack baseline to ≥60.0%.

**Branch**: `harness-60plus-iteration` off `origin/main` at commit `700af5f`.

**Plan**: [`plans/2026-05-13-harness-60plus-iteration.md`](../../plans/2026-05-13-harness-60plus-iteration.md).

> **Status**: in progress. This doc is a living artifact — phases are
> appended as evals land. Final write-up gates on the n=148 ≥60.0% run.

## Baseline (Phase 0)

`results/hf/sprint-2026-05-13/main-stack-run1/focusparse_focus_agentic_multi_page_333fe987.json`

| Metric             | Value              |
| ------------------ | ------------------ |
| Overall accuracy   | **49.3%** (73/148) |
| Datasheet accuracy | 54.5% (55/101)     |
| Finance accuracy   | 38.3% (18/47)      |
| Page recall        | 0.866              |
| Bbox IoU           | 0.799              |
| Lazy answer rate   | 0.081              |
| Tool calls / ex.   | 0.95               |
| Cost per correct   | $0.026             |

(Note: the `aggregate` block in the wrapper JSON reports the per-domain
slightly differently — 56.7% datasheet / 40.9% finance — because the
aggregate uses a different scorer pass. The per_example.jsonl numbers
above are the source of truth for sprint A/B.)

## Failure-mode triage (Phase 1)

`thoughts/shared/audits/2026-05-13-failure-triage.md`

| Bucket                        | Total | Datasheet | Finance |
| ----------------------------- | ----- | --------- | ------- |
| wrong_extraction_other        | 45    | 30        | 15      |
| wrong_page                    | 13    | 7         | 6       |
| bad_layout                    | 9     | 5         | 4       |
| lazy_abstain                  | 4     | 2         | 2       |
| wrong_extraction_normalizable | 4     | 2         | 2       |

`wrong_extraction_other` is dominated by `distant_evidence_fusion`
(16 datasheet) and `multi_chart_comparison` (6 dat + 3 fin). The
2026-05-11 prior holds: ~81% of failures are post-localization.

## Golden audit (Phase 2)

`thoughts/shared/audits/2026-05-13-golden-audit.md`

| Verdict          | Count |
| ---------------- | ----- |
| harness_error    | 74    |
| ambiguous        | 1     |
| unanswerable     | 0     |
| golden_incorrect | 0     |

~100% of the gap to 60% is fixable on our side. No clear upstream
benchmark fixes surfaced.

## Phase 3 iteration runs

### Run: 60plus-3a-3d-run1

**Stack**: Phase 3a v2 (question_family-gated finance prompt) +
Phase 3d (proactive non-abstain retry).

| Metric             | Run   | Δ vs baseline |
| ------------------ | ----- | ------------- |
| Overall accuracy   | (TBD) | (TBD)         |
| Datasheet accuracy | (TBD) | (TBD)         |
| Finance accuracy   | (TBD) | (TBD)         |
| Lazy answer rate   | (TBD) | (TBD)         |

(filled in once `results/hf/sprint-2026-05-13/60plus-3a-3d-run1/` lands)

## Phase 4 — Stopping condition

Goal: n=148 overall accuracy ≥ 60.0%, `lazy_answer_rate ≤ baseline + 1pp`,
`bbox_iou ≥ baseline − 2pp`, replication within ±2pp under
`--llm-cache-mode record-or-replay`.

## Commits landed on this branch

```
e32bef6  plans: add 2026-05-13 harness-60plus iteration plan
76858bd  layout: switch default endpoint to Modal + prefer modal token
6e285cb  audits: 2026-05-13 failure-mode triage on main-stack n=148
30afaf3  config: point layout endpoint at Modal in default.yaml
2641757  reasoner: Phase 3a per-domain exact_match prompt routing
ba311c5  audits: 2026-05-13 golden audit on main-stack failure set
223a12e  workflow: Phase 3d proactive non-abstain retry on lazy answers
a5002e0  scripts: 60plus sprint helper for per-domain run delta
76f5918  reasoner: Phase 3a v2 gate finance variant on question_family
```

(more rows appended as Phase 3 levers ship)
