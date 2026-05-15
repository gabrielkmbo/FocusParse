# 2026-05-13 Full-Run Failure Audit

This audit follows the user-requested split: for misses, decide whether the
problem is evidence collection / region detection, answer orchestration, provider
infrastructure, or a questionable benchmark question / gold answer.

## Scope

The browser screenshot shows the Hugging Face dataset viewer, but the viewer was
on a UI/default split. The run below used the repo-native loader:

- HF repo: `gabrielbo/parser-bench`
- HF revision: `3774c67f8b814392b6d04c939e904f749a3f52eb`
- Split loaded by harness: `validation`
- Raw validation rows filtered: 71 stress rows
- Canonical rows evaluated: 148
- Staging: `/Users/gabrielbo/.cache/focusparse/hf_staging_full_2026-05-13/benchmark.jsonl`
- Run: `results/hf/sprint-2026-05-13/full-modal-compact-normalized-run1/`

## Raw Result

| Metric | Value |
| --- | ---: |
| Accuracy | 48.6% (72/148) |
| Completed-row accuracy | 52.6% (72/137) |
| Provider/network failures | 11/148 |
| Cost | $1.766 |
| Cost per correct | $0.0245 |
| Mean latency | 3.53s |
| Page recall | 87.6% |
| Bbox IoU | 80.4% |
| Lazy answer rate | 8.1% |
| Tool calls/example | 0.93 |

The raw full-run number should not be treated as a clean accuracy claim because
11 rows failed before a real prediction was produced. Those rows have
`answer_pred=null`, no domain, no tools, zero tokens, and zero latency.

## Infrastructure Retry Follow-up

After adding provider retry hardening, a direct retry of one infra row with the
default cheap planner still failed before planning because Gemini returned
`429 RESOURCE_EXHAUSTED`. Re-running the same infra slice with
`--tier-override planner=mid --tier-override router=mid` bypassed the exhausted
cheap tier and produced real predictions for all 11 previously-null examples:

| Metric | Value |
| --- | ---: |
| Retry-slice accuracy | 54.5% (6/11) |
| Retry-slice cost | $0.176 |
| Retry-slice cost per correct | $0.0293 |
| Retry-slice mean latency | 5.62s |
| Retry-slice page recall | 77.3% |
| Retry-slice bbox IoU | 65.5% |
| Tools selected | `inspect_region+expand_context` on all 11 |

If those 11 retry outcomes replaced the full run's null infrastructure rows,
the raw full-run score would move from 72/148 = 48.6% to 78/148 = 52.7%. That
matches the completed-row diagnosis: provider reliability is a real source of
noise, but it is not enough to reach 60%. The remaining lift has to come from
answer extraction, scorer-shape discipline, and hard visual reasoning.

Representative retry outcomes:

- `dat-ads1299-0023`: recovered to correct (`Gain = 24`) with high IoU.
- `dat-JESD204B-Survival-Guide-0029`: recovered to correct (`6`) with high IoU.
- `dat-spruhm8k-0019`: high-IoU evidence but exact answer ordering / list shape
  still failed (`ADC_readPPBResult; ADC_setINLTrim; ADC_readResult` vs gold
  order).
- `dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047`:
  near numeric miss (`316 mJ` vs `315 mJ`), worth checking tolerance policy.
- `dat-ads1299-0028`: remained `Unanswerable` after verifier rejection, so this
  is an evidence/routing or verifier-control miss rather than provider noise.

## Failure Taxonomy

| Category | Count | Interpretation |
| --- | ---: | --- |
| Correct | 72 | Scored correct. |
| Infrastructure failure | 11 | Provider timeout / network failure before usable prediction. |
| Page or routing miss | 9 | Wrong or incomplete page set, often multi-page evidence. |
| Region or evidence miss | 9 | Correct page but missing / wrong supporting crop. |
| Answer, scorer, or reasoning miss | 47 | Evidence was mostly present; final answer was wrong, too verbose, under-normalized, or semantically close but not scorer-compliant. |

The main degradation is therefore not the Modal layout endpoint. Modal returned
healthy 200 responses throughout the run. The largest completed-row failure
bucket is answer/scorer/reasoning, followed by smaller routing and evidence
collection buckets.

## Dynamic Tool Use

The full run did not force all +4 tools:

| Selected tools | Rows | Accuracy | Cost | Mean latency |
| --- | ---: | ---: | ---: | ---: |
| none (infra failure) | 11 | 0.0% | $0.000 | 0.00s |
| `inspect_region` | 55 | 58.2% | $0.606 | 3.47s |
| `inspect_region+expand_context` | 82 | 48.8% | $1.160 | 4.05s |

`expand_context` is being selected for harder rows, not sprayed everywhere. The
lower accuracy in the `inspect_region+expand_context` bucket should not be read
as the tool causing failure without matched difficulty controls.

## Why Accuracy Degraded Below the 30-Row Slice

1. The 30-row slice overestimated generalization. The first 30 rows hit 66.7%
   live and projected higher with deterministic answer normalization, but the
   remaining 118 rows include harder finance charts, multi-page comparisons,
   dense tables, and figure-level visual reasoning.
2. Provider/network failures contaminated the full run. Even if every one of
   the 11 infra rows were later correct, the maximum raw score for this artifact
   would be 83/148 = 56.1%, so infra is not the only blocker.
3. Region grounding is improved but not sufficient. Completed rows had strong
   page recall and IoU overall, yet 47 misses had evidence present enough that
   the next bottleneck is answer extraction, numeric/chart reasoning, or scorer
   shape.
4. Several benchmark rows are scorer-shape traps. Some predictions are
   semantically close or arguably acceptable, but exact-match scoring rejects
   abbreviations, extra explanation, or equivalent abstention wording.

## Example Misses by Category

### Infrastructure

- `dat-ads1299-0023`, `dat-ads1299-0028`,
  `dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0012`,
  `dat-spruhm8k-0019`, `fin-jpm_ltcma-0005`, and six others failed before
  prediction due provider timeouts or network reachability. These should be
  retried, not scored as harness reasoning failures.

### Evidence / Region / Routing

- `fin-aapl-20250927-0021`: predicted `Unanswerable`; page recall 0.5 and low
  IoU, so the fiscal-year/classification evidence was incomplete.
- `dat-arm1176-ch3-coproc.annot-0052`: predicted `Unanswerable`; correct page
  but IoU 0.0, so the crop missed the figure/register region.
- `dat-DS5091D-00-0016`: predicted `8 us` vs gold `~13 us`; correct page but
  low IoU, consistent with wrong waveform segment.
- `fin-bis_qr_2025_mar-0061` and `0062`: correct page but low IoU, suggesting
  the cited chart region was too broad or not the exact panel.

### Answer / Reasoning / Scorer Shape

- `dat-Arm_EE382N_4-0001`: right page and IoU 0.996, but the VLM reads `50%`
  instead of `70%`.
- `dat-adrv9040-reference-manual-ug-2192-0052`: right page and IoU near 1.0,
  but counting inside visually similar boxes remains wrong.
- `fin-vis-jpm_gtm_us_daily-0109`: right chart region, but negative-return
  count is `5` instead of `3`.
- `fin-fed_fsr_2023_apr-0063`: right chart region, but axis interpretation is
  wrong: predicts `30-year` instead of `10-year`.
- `dat-opa454-0018`: right chart region, but numeric interpolation is wrong:
  predicts `-800 mV` vs gold `-400`.

### Needs Benchmark / Scorer Audit

These are not necessarily wrong gold answers, but they are candidates where the
scorer or gold wording should be audited before drawing scientific conclusions:

- `fin-imf_weo_2024_oct-0003`: prediction `Unanswerable`; gold says
  `None - no topic...`. This is semantically close to an abstention.
- `dat-SG017_2022-0053`: gold allows `RTQ2532W or RTQ2532N`; prediction gives
  `RTQ2532W, 2000`. This may be acceptable if either part number satisfies the
  question.
- `fin-bis_qr_2024_sep-0063`: prediction `FR...`; gold says `France (FR)...`.
  This is an abbreviation/scorer-shape issue.
- `fin-boe_fsr_2024_nov-0056`: prediction starts with `Germany`; gold is
  `Germany`. Exact-match scoring rejects the added explanation.
- `dat-arm1176-ch3-coproc.annot-0004`: prediction `0x00000000`; gold
  `0 (reset value)`. This needs a policy decision on equivalent zero formats.

## Next Actions

1. Add provider-call retry hardening before the next publishable run.
2. Retry the 11 infrastructure-failed rows and report both raw and
   infra-adjusted accuracy.
3. Build a compact miss-audit artifact for the 65 completed wrong rows, with
   the exact HF question/gold/prediction and category.
4. Continue answer-shape normalization only when it is question-gated and
   benchmark-general, not id keyed.
5. For chart/count rows, improve tool orchestration by adding dynamic
   chart/table or structured counting support only when the question asks for
   counting, interpolation, or axis comparison.
