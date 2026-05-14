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

### Run: 60plus-3a-3d-run1 (killed at 40/148 — Gemini free-tier quota)

**Stack**: Phase 3a v2 (question_family-gated finance prompt) +
Phase 3d (proactive non-abstain retry on lazy answers with citations).

The eval hit Gemini's free-tier 20-req/day quota and started returning
429 `RESOURCE_EXHAUSTED` on every planner+router call. Killed at
example 40. Partial directional signal on the 39 examples that
completed cleanly (alphabetical order; 31 datasheets + 9 finance —
finance-light vs the full 101+47 split):

| Slice (n=39)     | main-stack | 3a+3d run1 | Δ           |
| ---------------- | ---------- | ---------- | ----------- |
| Overall accuracy | 53.8% (21) | 66.7% (26) | **+12.8pp** |
| Datasheet (n=30) | 60.0% (18) | 73.3% (22) | +13.3pp     |
| Finance (n=9)    | 33.3% (3)  | 44.4% (4)  | +11.1pp     |

Six examples flipped to correct, one flipped to wrong:

| example_id                           | base → new pred                 | gold                             | mechanism           |
| ------------------------------------ | ------------------------------- | -------------------------------- | ------------------- |
| `dat-Arm_EE382N_4-0028`              | `EXECUTE MEMORY WRITE` → MEMORY | `MEMORY; it occurs after…`       | prompt change       |
| `dat-DS5091D-00-0002`                | `0 ppt` → `2 ppt`               | `Approximately 3%`               | chart re-read       |
| `dat-adrv9040-…-0032`                | `…641 kb` → `…, 641 kb`         | `…, 641 kb`                      | comma format fix    |
| `dat-adrv9040-…-0041`                | long sentence → `DPD_MODE1`     | `DPD_MODE1; this is visually…`   | prompt change       |
| `dat-aducm350_ug-587-0032`           | `Unanswerable` → `b0010`        | `b0010`                          | **Phase 3d retry**  |
| `fin-10-K-0036`                      | `82%` → `68%`                   | `68%`                            | unknown (variance?) |
| `dat-Arm_EE382N_4-0006` (regression) | `1.0` → `1.2`                   | `aspect ratio approximately 1.0` | reasoner variance   |

Phase 3d's lazy-abstain recovery is mechanism-confirmed
(`dat-aducm350_ug-587-0032` is one of the 4 `lazy_abstain` rows in
the triage). Phase 3a v2 finance variant didn't yet fire visibly in
the first-40 slice because most early finance examples are not in
the sentence-form families.

### Run: 60plus-3a-3d-oai-nano-run1 (full n=148, **landed**)

`results/hf/sprint-2026-05-13/60plus-3a-3d-oai-nano-run1/focusparse_focus_agentic_multi_page_8c5e328d.json`.

After burning through both Gemini free-tier daily quotas
(gemini-2.5-flash + gemini-2.5-flash-lite, 20 req/day each) and
seeing Anthropic Haiku zero out the Phase 3a v2 + 3d gain, the
fallback `cheap_oai` tier (OpenAI `gpt-4.1-nano`) was wired in
(`configs/default.yaml`) and used via
`FOCUSPARSE_TIER_PLANNER=cheap_oai FOCUSPARSE_TIER_ROUTER=cheap_oai`.

| Metric               | Run                 | Δ vs main-stack   |
| -------------------- | ------------------- | ----------------- |
| Overall accuracy     | **52.03%** (77/148) | **+2.7pp**        |
| Page recall          | 0.913               | +0.047            |
| Bbox IoU             | 0.843               | +0.044            |
| **Lazy answer rate** | **0.027**           | **−0.054 (−54%)** |
| Cost per correct     | $0.028              | +$0.002           |
| Total cost           | $2.13               | +$0.24            |

**Phase 3d's lazy-abstain recovery is fully confirmed** at scale:
8 of the 12 baseline lazy abstentions were recovered into concrete
answers. Localizer metrics also improved (Modal endpoint healthier
than the paused HF endpoint).

Net delta is small because the cheap-tier model dominates the
planner+router decisions — OpenAI `gpt-4.1-nano` is a meaningfully
weaker planner than Gemini Flash on this benchmark. The killed
Gemini-cheap partial showed +12.8pp on n=39, which extrapolates to
~62% if it scales; this OAI fallback shows the _Phase 3a v2 + 3d
intrinsic contribution_ without that benefit.

**Headline interpretation**: at +2.7pp from Phase 3a v2 + Phase 3d
alone we're short of the 60% target. The path forward depends on
when Gemini cheap-tier quota resets (next bullet) and whether
additional levers (Phase 3b self-consistency, multi_scale_packets)
stack on top.

### Quota-blocked: rerun under Gemini cheap once daily quota resets

The Gemini free-tier daily quota resets at midnight Pacific. The
2026-05-13 sprint burned both `gemini-2.5-flash` and
`gemini-2.5-flash-lite` (20 req/day each, our planner+router does
~2 calls/example × 148 = 296). The next viable Gemini-cheap n=148
run lands after ~22 hours from quota exhaustion.

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
