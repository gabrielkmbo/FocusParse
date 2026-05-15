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

### Run: 2026-05-14 reasoner-escalation gating slices

**Question**: should verifier `next_action="escalate_reasoner"` spend a
default retry? The 52.0% OAI fallback run had 24 initial
`escalate_reasoner` rows: 10 were wrong and 14 were already scorer-correct
despite verifier disagreement. That is the exact non-cherry-picked control set
for this question.

**Code change**: `_should_allow_reasoner_shape_retry` now keeps generic
`escalate_reasoner` behind the explicit full-loop budget, but allows one
default retry when:

- the answer cites evidence,
- the verifier rejected it,
- the answer type is exact/numeric/string, and
- the answer is visibly explanatory/prose-shaped when the verifier reason is
  also about format/direct-answer failure.

The existing single-entity/list-like exception remains. New workflow tests pin
the three important guardrails: verbose numeric prose retries, concise exact
answers do not retry, and boolean answers do not enter the path.

#### Slice A — shape-gated default

`results/hf/sprint-2026-05-14/escalate-shape-retry-slice-run1/`

| Metric                      | Value         |
| --------------------------- | ------------- |
| Slice accuracy vs prior run | 79.2% (19/24) |
| Prior-run slice accuracy    | 58.3% (14/24) |
| Net delta                   | **+5 rows**   |
| Prior wrong recovered       | 5/10          |
| Prior correct regressed     | **0/14**      |
| Rows with any retry         | 5/24          |
| Total cost                  | $0.348        |

Important caveat: the +5 slice gain is not fully attributable to the new retry
gate. Several recovered rows were fixed on the first sampled answer in the new
run (`retries_used=0`), so upstream sampling variance is still mixed in. The
stronger claim is the guardrail claim: the shape-gated policy preserved all 14
prior-correct verifier false-negatives on this control set.

Useful recoveries:

| example_id                                   | prior prediction                                 | new prediction                                | gold       |
| -------------------------------------------- | ------------------------------------------------ | --------------------------------------------- | ---------- |
| `dat-adrv9040-reference-manual-ug-2192-0052` | `LOGGING and MULTI-THREADING ... 6 functions`    | `LOGGING and MULTI-THREADING ... 7 functions` | same       |
| `dat-spruhm8k-0025`                          | prose about left-shifting and ignoring bits      | `0x3FFFF8; 0x3FFFF`                           | `0x3FFFF8` |
| `fin-bis_qr_2025_mar-0040`                   | long EMEU explanation with scatterplot rationale | `EMEU`                                        | `EMEU`     |

#### Slice B — broad full-loop retry (`--max-retries 1`)

`results/hf/sprint-2026-05-14/escalate-all-reasoner-slice-run1/`

| Metric                      | Value         |
| --------------------------- | ------------- |
| Slice accuracy vs prior run | 54.2% (13/24) |
| Prior-run slice accuracy    | 58.3% (14/24) |
| Net delta                   | **−1 row**    |
| Prior wrong recovered       | 3/10          |
| Prior correct regressed     | **4/14**      |
| Rows with any retry         | 21/24         |
| Total cost                  | $0.321        |

Broad retry proves the negative control: verifier disagreement alone is not a
safe dynamic signal. It recovers some wrong rows, but it also damages concise
answers that were already scorer-correct:

| example_id                 | prior correct answer  | broad-retry answer            |
| -------------------------- | --------------------- | ----------------------------- |
| `dat-spruhm8k-0002`        | `3 lines`             | `8`                           |
| `fin-aapl-20250927-0034`   | `September 2022, $21` | `September 2023, $19`         |
| `fin-bis_qr_2024_sep-0050` | `FX bonds`            | `C. FX bonds and D. FX loans` |

**Decision**: keep `escalate_reasoner` dynamic and gated. Do not force all
verifier escalations through a retry, and do not treat +4 tool availability as
"always use all tools." The next publishable check is a full n=148 run under
the shape-gated default, ideally with an LLM cache for planner/reranker to
reduce upstream sampling noise.

### Quota-blocked: rerun under Gemini cheap once daily quota resets

The Gemini free-tier daily quota resets at midnight Pacific. The
2026-05-13 sprint burned both `gemini-2.5-flash` and
`gemini-2.5-flash-lite` (20 req/day each, our planner+router does
~2 calls/example × 148 = 296). The next viable Gemini-cheap n=148
run lands after ~22 hours from quota exhaustion.

### Run: shape-gated reasoner retry, full OAI n=148 (**current best**)

`results/hf/sprint-2026-05-14/escalate-shape-retry-oai-run1/focusparse_focus_agentic_multi_page_8c5e328d.json`.

This is the full n=148 check for the dynamic `escalate_reasoner` policy above.
It uses the Modal layout endpoint, `cheap_oai` planner/router overrides, and the
shape-gated default retry policy. It is the current best full-table harness
result.

| Metric             | Run                 | Δ vs main-stack | Δ vs 3a+3d-OAI |
| ------------------ | ------------------- | --------------- | -------------- |
| Overall accuracy   | **57.43%** (85/148) | **+8.1pp**      | **+5.4pp**     |
| Datasheet accuracy | 64.4% (65/101)      | +9.9pp          | +6.9pp         |
| Finance accuracy   | 42.6% (20/47)       | +4.3pp          | +2.1pp         |
| Page recall        | 0.921               | +0.055          | +0.008         |
| Bbox IoU           | 0.851               | +0.052          | +0.009         |
| Lazy answer rate   | 0.034               | -0.047 (-58%)   | +0.007         |
| Cost per correct   | $0.025              | -$0.001         | -$0.003        |
| Total cost         | $2.10               | +$0.21          | -$0.03         |
| Mean latency       | 4.37s               | +0.51s          | -0.02s         |

Compared with the clean OAI run on the common 147-row set, the shape-gated
default recovered 17 prior-wrong rows and regressed 9 prior-correct rows
(net +8). The top-line file has 85/148 vs 77/148, so the full-table gain is
+8 rows.

The run is still **4 correct answers short of 60%**. Its 63 remaining wrong
rows are 36 datasheet and 27 finance. The wrong-row diagnostics point away from
layout as the main remaining bottleneck: only 11 wrong rows have page recall
below 1, and only 12 have bbox IoU below 0.5. The dominant gap is still
post-evidence answer extraction / scorer-shape, especially verifier decisions
that accepted or exhausted with plausible but scorer-wrong spans.

### Control: expanded technical vocabulary gate (not shipped)

`results/hf/sprint-2026-05-14/escalate-vocab-gate-slice-run1/`.

After inspecting failures such as "which instruction", "which mode", and
"which loop", a broader single-entity vocabulary gate was tested on every row
from the full run whose initial verifier action was `escalate_reasoner`
(29 rows, including prior-correct controls).

| Metric                  | Value      |
| ----------------------- | ---------- |
| Prior full-run slice    | 13/29      |
| New slice               | 13/29      |
| Net delta               | **0 rows** |
| Prior wrong recovered   | 3 rows     |
| Prior correct regressed | 3 rows     |
| Retries observed        | 0 in flips |

Decision: do **not** ship the broader vocabulary gate. The apparent recoveries
are mostly initial-answer sampling variance (`retries_used=0`), and the equal
number of regressions fails the generalized-technique bar.

### Run: Phase 3b K=2 reasoner self-consistency (negative)

`results/hf/sprint-2026-05-14/self-consistency-k2-oai-run1/focusparse_focus_agentic_multi_page_8c5e328d.json`.

K=2 reasoner self-consistency was tested as a full-table answer-extraction
lever on the `phase3b-self-consistency` branch. It runs two initial reasoner
samples and picks with the committed heuristic (non-Unanswerable, more
citations, shorter for exact/numeric/boolean/multiple-choice, higher
confidence).

| Metric             | K=2 run             | Δ vs current best |
| ------------------ | ------------------- | ----------------- |
| Overall accuracy   | **52.70%** (78/148) | **-4.7pp**        |
| Datasheet accuracy | 59.4% (60/101)      | -5 rows           |
| Finance accuracy   | 38.3% (18/47)       | -2 rows           |
| Page recall        | 0.903               | -0.018            |
| Bbox IoU           | 0.827               | -0.024            |
| Lazy answer rate   | 0.034               | flat              |
| Reported cost      | $2.10               | flat              |
| Mean latency       | 3.96s               | -0.41s            |

Common-set flip analysis vs the current best run (147 shared rows): K=2
recovered 5 prior-wrong rows but regressed 12 prior-correct rows (net -7).
Regressions include scorer-critical over/under-extraction:
`dat-adrv9040-...-0052` (`LOGGING and MULTI-THREADING` ->
`LOGGING, 6`), `fin-10-K-0036` (`68%` -> `84%`), and
`dat-aducm350_ug-587-0052` (`SRAM0 ... SRAM1` -> unrelated bus terms).

Decision: K=2 self-consistency should remain opt-in, not default. The current
picker is too weak: a second sample adds another chance to pick a plausible but
wrong span. Future answer-selection work should use verifier/scorer-aware
selection or evidence-grounded answer normalization, not naive K-sample picking.

Pricing caveat: this run also exposed that per-example headline `usd` is
answer-stage telemetry, not full trace cost, and the pre-fix K=2 telemetry
counted only the chosen sample. The workflow now returns aggregated K-sample
tokens/cost for answer telemetry, but historical run JSONs before this fix
understate K=2 pricing.

### Run: Phase 3e strict-shape verifier v2, matched K=1 (negative)

`results/hf/sprint-2026-05-14/strict-shape-v2-oai-run1/focusparse_focus_agentic_multi_page_8c5e328d.json`.

This run tests the current branch's narrowed exact-match strict-shape verifier
prompt at K=1, with the same HF revision, staging dir, Modal endpoint, and
`cheap_oai` planner/router setup as the current 57.4% best. It is therefore the
clean matched check for whether Phase 3e helps without K=2.

| Metric             | Strict-shape v2     | Δ vs current best |
| ------------------ | ------------------- | ----------------- |
| Overall accuracy   | **56.76%** (84/148) | **-0.7pp**        |
| Datasheet accuracy | 62.4% (63/101)      | -2 rows           |
| Finance accuracy   | 44.7% (21/47)       | +1 row            |
| Page recall        | 0.903               | -0.018            |
| Bbox IoU           | 0.848               | -0.003            |
| Lazy answer rate   | 0.047               | +0.014            |
| Reported cost      | $2.17               | +$0.07            |
| Mean latency       | 3.57s               | -0.80s            |

Unique-id flip analysis vs current best: 9 recovered rows and 10 regressed
rows (net -1 unique row). Recoveries include useful exact-shape fixes:
`dat-DS5091D-00-0011` (`Return the manufacturer ID number : 0x00h` -> `0x00h`),
`dat-adrv9040-...-0041` (long DPD prose -> `DPD_MODE1`), and
`fin-aapl-20250927-0034` (table-row spill -> `September 2022, $21`).
Regressions show why the rule should not become the new default:
`dat-adrv9040-...-0032` lost the comma in `ADRV9040_FW.bin, 641 kb`,
`dat-adrv9040-...-0052` collapsed a tie to `LOGGING, 6`, and
`fin-boe_fsr_2024_nov-0056` drifted from `Germany` to `UK and US`.

Decision: Phase 3e strict-shape v2 remains a useful diagnostic prompt, but it
does not improve the full-table default. The next path should target evidence
quality for chart/visual rows or use a stronger verifier-aware answer selector,
not prompt-only strictness.

### Candidate still open: multi-scale packets

`--multi-scale-packets` remains a plausible next lever for chart-heavy failures:
the inspector renders both a tight crop and a wider context crop per region, and
the reasoner sees both via `EvidencePacket.multi_scale_crops`. It still needs a
matched full n=148 run against the 57.4% current best before it can be claimed.

### Run: multi-scale packets, matched K=1 (negative)

`results/hf/sprint-2026-05-14/multiscale-k1-oai-run1/focusparse_focus_agentic_multi_page_8c5e328d.json`.

This run tests `--multi-scale-packets` on the current branch with K=1. It gives
the reasoner both tight and context crops per evidence packet. The run was
stable, but it did not improve the full-table result and it materially increased
reported answer-stage cost.

| Metric             | Multi-scale K=1     | Δ vs current best |
| ------------------ | ------------------- | ----------------- |
| Overall accuracy   | **56.08%** (83/148) | **-1.4pp**        |
| Datasheet accuracy | 61.4% (62/101)      | -3 rows           |
| Finance accuracy   | 44.7% (21/47)       | +1 row            |
| Page recall        | 0.904               | -0.017            |
| Bbox IoU           | 0.839               | -0.012            |
| Lazy answer rate   | 0.047               | +0.014            |
| Reported cost      | $4.39               | +$2.29            |
| Cost per correct   | $0.053              | +$0.028           |
| Mean latency       | 6.84s               | +2.47s            |

Compared with the 57.4% current best on the shared unique-id set, multi-scale
recovered 7 rows and regressed 9 rows. The recoveries show the intended
mechanism in a few cases (`dat-ads1299-0057`: `32 t_CLK` -> `16 t_CLK`;
`dat-gmsl2-...-0023`: long comparison -> `different`), but the regressions are
also evidence-shape regressions (`dat-JESD204B-...-0029`: `6` -> `Unanswerable`;
`dat-ads1299-0064`: `0.35 uVpp` -> `0.25 uVpp`). This suggests that always
showing more visual context creates distractors as often as it resolves missing
context.

Decision: keep multi-scale packets off by default. A future version may still
be useful if gated to specific chart/readability families or verifier requests,
but unconditional multi-scale is not the path to 60%.

### Run: chart-to-table with generic-chart fallback, matched K=1 (negative)

`results/hf/sprint-2026-05-15/chart-fallback-ctt-oai-run1/focusparse_focus_agentic_multi_page_8c5e328d.json`.

This run tests a dynamic chart-tool fallback: when a chart-family question asks
for chart evidence and reranker marks a generic visual (`figure_class=other` or
`screenshot`) as primary/high-relevance, the inspector can add chart context and
run `chart_to_table`. A smoke run on `fin-vis-jpm_gtm_us_daily-0109` validated
the intended mechanism (`2` -> `3`, matching gold `3 times`), but the full
first-pass chart-to-table run regressed overall.

| Metric             | Chart fallback + CTT | Δ vs current best |
| ------------------ | -------------------- | ----------------- |
| Overall accuracy   | **54.05%** (80/148)  | **-3.4pp**        |
| Datasheet accuracy | 60.4% (61/101)       | -4 rows           |
| Finance accuracy   | 40.4% (19/47)        | -1 row            |
| Page recall        | 0.914                | -0.007            |
| Bbox IoU           | 0.833                | -0.018            |
| Lazy answer rate   | 0.027                | -0.007            |
| Reported cost      | $2.19                | +$0.09            |
| Cost per correct   | $0.027               | +$0.003           |
| Mean latency       | 5.30s                | +0.92s            |

Flip analysis vs the 57.4% current best: 7 recovered rows, 12 regressed rows
(net -5). The new generic fallback itself was promising but too broad before
tightening: fallback rows were 8/12 correct with 3 recoveries
(`fin-vis-jpm_gtm_us_daily-0109`, `dat-adrv9040-...-0041`,
`dat-gmsl2-...-0023`) and 1 regression (`dat-aducm350_ug-587-0052`). The full
`chart_to_table` flag was the larger problem: it attempted on 48 rows, produced
CSV on 36, but those CSV rows were only 14/36 correct and introduced several
explicit-chart regressions (`dat-DS5091D-00-0016`, `fin-boe_fsr_2024_nov-0056`,
`fin-boj_fsr_2024_oct-0008`).

Decision: keep `--chart-to-table` off as a first-pass default. The generic
fallback was tightened after this run so ambiguous chart-like families such as
`dual_axis_disambiguation` only treat `figure_class=other` as chart-like when
the planner explicitly requests `evidence_types=["chart", ...]`. The next
chart path should be verifier-triggered repair or fallback-only extraction, not
global chart-to-table on every explicit chart region.

### Run: tightened generic-chart context only, matched K=1 (new best)

`results/hf/sprint-2026-05-15/chart-fallback-context-only-oai-run1/focusparse_focus_agentic_multi_page_8c5e328d.json`.

This run keeps the tightened generic-chart fallback but leaves
`--chart-to-table` off. It isolates the useful part of the chart experiment:
dynamic ranking/context for planner-confirmed chart evidence, without noisy
first-pass CSV extraction.

| Metric             | Context-only fallback | Δ vs prior best |
| ------------------ | --------------------- | --------------- |
| Overall accuracy   | **58.78%** (87/148)   | **+1.4pp**      |
| Datasheet accuracy | 64.4% (65/101)        | flat            |
| Finance accuracy   | 46.8% (22/47)         | +2 rows         |
| Page recall        | 0.911                 | -0.010          |
| Bbox IoU           | 0.846                 | -0.006          |
| Lazy answer rate   | 0.034                 | flat            |
| Reported cost      | $2.12                 | +$0.02          |
| Cost per correct   | $0.024                | flat            |
| Mean latency       | 3.80s                 | -0.58s          |

Unique-id flip analysis vs the 57.4% prior best: 9 recovered rows and
7 regressed rows (net +2). Useful recoveries include `fin-aapl-20250927-0034`
(`September 2022, $21`), `fin-vis-jpm_gtm_us_daily-0126` (`UK`),
`fin-bis_qr_2025_mar-0050` (`Latvia`), `dat-gmsl2-...-0023` (`Different`),
and `dat-ads1299-0057` (`16 t_CLK`). Regressions are mostly answer-shape or
over-inclusion rather than localization failures: `dat-adrv9040-...-0052`
adds `, 6`; `fin-bis_qr_2024_sep-0050` adds `D. FX loans`; and
`dat-arm1176-ch3-coproc.annot-0004` answers with a full sentence instead of
the compact value `0`.

Decision: this becomes the new current best, but the goal is not complete.
The harness still needs two more correct rows to cross 60%. The next lever
should target answer-shape/selection on already-localized evidence, not broader
first-pass visual tooling.

## OAI-cheap current ceiling: 58.8%

With `cheap_oai` (gpt-4.1-nano) planner/router, the best measured full-stack
run is now **58.78%**. Broad "more context/tooling" changes still regress, but
the tightened chart-context fallback shows that narrow, evidence-confirmed
orchestration can move the table.

| Stack addition                     | Δ vs 57.4% prior best |
| ---------------------------------- | --------------------- |
| Phase 3e v1 (strict shape)         | -4.7pp                |
| Phase 3e v2 (narrowed shape)       | -0.7pp                |
| multi_scale_packets                | -1.4pp                |
| chart_to_table + generic fallback  | -3.4pp                |
| tightened chart-context fallback   | +1.4pp                |

The next two-row gap is unlikely to close by adding more first-pass evidence.
Most remaining recoverable rows already have page recall / IoU signal; the
highest-leverage path is answer-shape repair or verifier-aware selection over
existing evidence.

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
