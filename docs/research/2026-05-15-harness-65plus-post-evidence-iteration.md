# FocusParse 65%+ Post-Evidence Iteration

Date: 2026-05-15  
Branch/worktree: `codex/harness-65plus-iteration` at `/private/tmp/focusparse-harness-65plus-iteration`

## Objective

Push the merged 60.14% FocusParse harness checkpoint toward 65%+ accuracy
without benchmark-gold leakage, example-id-specific rules, cherry-picking, or
broadly forcing more tools.

Canonical baseline:

`results/hf/sprint-2026-05-15/answer-shape-normalizer-oai-run2/focusparse_focus_agentic_multi_page_8c5e328d.json`

Baseline summary: 89/148 = 60.14%; datasheet 64/101, finance 25/47;
cost/correct $0.0243; mean latency 4.26s; page recall 0.892; bbox IoU 0.870;
lazy-answer rate 0.041.

## Method

I used a 60-row mixed target/control slice before any full n=148 run:

- 40 target rows from
  `results/agent_eyes/2026-05-15-answer-shape-normalizer-wrong/agent_eyes_audit.jsonl`
- 20 prior-correct controls from the same 60.14% baseline run
- Same HF validation revision as the baseline:
  `3774c67f8b814392b6d04c939e904f749a3f52eb`
- Same full tool set and dynamic tool usage
- Gate: continue to full n=148 only if recoveries - regressions > 0 and
  prior-correct control regressions <= 1

The slice id file is:

`results/slices/2026-05-15-contract-guard-target-control-ids.txt`

## Implemented Changes

Commit `3b5c486`: added a gold-free answer-contract layer inferred from
question text, domain, answer type, and question family. The contract feeds the
reasoner/verifier prompts, blocks severe verifier false-accepts after verifier
parsing, emits `answer_shape_failure` diagnostics, and enables one
same-evidence reasoner retry for contract failures. Also added
`--example-ids-file` to `scripts/run_hf_eval.py`.

Commit `aec9913`: added derived evidence groups without changing
`EvidenceEvent`. Table groups bind primary packet text to row/header/unit/test
condition/note/caption context. Chart groups bind plot area to legend, axes,
caption, and footnotes. Reasoner and verifier prompts receive this grouped
view.

Commit `02ce712`: restored packet-level descriptors alongside evidence groups
in the reasoner prompt after grouped-only prompting caused over-abstention and
control regressions.

Commit `400ca53`: added additional gold-free answer-shape normalization for
verbose boolean answers, verbose finance accounting negatives, and OCR-ish
hex/register spans such as `OxFF (SERDINO to SERDIN7)`.

Commit `4296de2`: added `--minimal-artifacts` for disk-constrained slice
experiments. This keeps the wrapper JSON, `run.json`, and `per_example.jsonl`
while skipping per-row prediction-cache JSONs and agentic tile PNGs.

Commit `32331a1`: treated 429/rate-limit responses as transient model errors
so eval runs can use the existing retry/backoff environment variables instead
of counting provider throttling as benchmark failures.

Commit `2b145a9`: added a narrow exact-match normalizer for leading code-like
identifiers followed by explanations, e.g. `DPD MODE1. ...` -> `DPD_MODE1`.

Commit `71df0b1`: added corresponding-row and checkbox-binding contract cues.
These cues tell the reasoner/verifier to bind the source row/year/entity before
reading a corresponding output field, and to bind checkbox marks to their
nearest Yes/No or status labels. The verifier now propagates
`checkbox_binding_risk` diagnostics for a same-evidence reasoner retry.

Commit `16192a9`: recorded the row-binding contract checkpoint in project
memory.

## Slice Results

| Run | Correct | Accuracy | Cost | Cost/correct | Latency mean | Page recall | Bbox IoU | Lazy rate | Recoveries | Regressions | Net | Control regressions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| contract guard | 17/60 | 28.3% | $0.843 | $0.050 | 4.43s | 0.942 | 0.934 | 0.017 | 3 | 6 | -3 | 6 |
| evidence groups | 16/60 | 26.7% | $0.827 | $0.052 | 4.08s | 0.903 | 0.835 | 0.067 | 3 | 7 | -4 | 7 |
| hybrid groups + packets | 19/60 | 31.7% | $0.905 | $0.048 | 4.14s | 0.931 | 0.911 | 0.033 | 6 | 7 | -1 | 7 |
| answer-shape guard minifacts run1 | 22/60 | 36.7% | $0.851 | $0.039 | 3.95s | 0.961 | 0.900 | 0.017 | 4 | 2 | +2 | 2 |
| leading identifier minifacts run2 | 20/60 | 33.3% | $0.848 | $0.042 | 4.09s | 0.978 | 0.933 | 0.000 | 3 | 3 | 0 | 3 |

The first disk-light answer-shape run was the best clean slice so far, but it
still failed the mixed-slice gate because prior-correct control regressions
were 2, above the <=1 threshold. A follow-up run after the leading identifier
patch was worse (net 0, 3 control regressions), showing that the remaining
control failures are not only deterministic shape normalization issues.

One earlier disk-light attempt was discarded as invalid: it hit an Anthropic
429 rate-limit error mid-run and the harness converted affected rows to error
records. Those rows are not counted as evidence for accuracy or flips.

A row-binding slice attempt after commit `71df0b1` was stopped before result
artifacts were written because the planner hit Gemini free-tier daily quota
(`gemini-2.5-flash`, 20 requests/day) and began producing provider-error rows.
It is not counted as evidence. Re-run the same 60-row slice once quota is
available or the planner tier is moved to a non-quota-blocked provider.

## Qualitative Flips

Useful recoveries in the hybrid run:

- `dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047`
  recovered from a row label to `315 mJ`.
- `dat-adrv9040-reference-manual-ug-2192-0052` recovered the tied multi-field
  answer: `LOGGING and MULTI-THREADING are tied at 7 functions each`.
- `fin-aapl-20250927-0034` recovered the month/value shape:
  `September 2022, $21`.
- `dat-Arm_EE382N_4-0049` recovered a concise label plus meaning:
  `BLE; Signed integer comparison gave less than or equal`.

Representative regressions:

- `fin-10-K-0010`: baseline `-40` regressed to a verbose accounting-form answer
  `$(40) million; ...`. Semantically right, scorer-shape wrong.
- `fin-aapl-20250927-0010`: baseline `yes` regressed to a verbose yes answer.
- `dat-adrv9040-reference-manual-ug-2192-0051`: baseline
  `0xFF (SERDIN0 to SERDIN7)` regressed through OCR-ish casing:
  `OxFF (SERDINO to SERDIN7)`.
- `dat-Arm_EE382N_4-0001`: baseline `60%` regressed to `40%`, showing that
  grouping did not solve all visual/diagram proportion ambiguities.
- `fin-aapl-20250927-0002`: baseline `180,683; typical` regressed to
  `169,148; minimum`, a wrong-row table/column selection issue.
- `fin-aapl-20250927-0010`: baseline `yes` regressed to `no` in run2,
  indicating that boolean controls still need evidence-grounded adjudication,
  not just answer-shape collapse.

## Interpretation

The core hypothesis was right in direction but incomplete in mechanism:
post-evidence packaging and contracts do recover high-recall/high-IoU failures,
especially label-vs-value and multi-field rows. However, prompt-only grouping
also increases answer verbosity, over-abstention, and OCR-looking span drift on
previously correct controls.

The best clean slice now shows positive net flips (+2), which is encouraging,
but the control-regression gate still blocks a full n=148 run. The remaining
regressions are mostly wrong-row / wrong-series decisions, not syntax-only
shape mistakes.

The next mechanism should not be broader retrieval or another prompt-only full
run. The next step should be gated repair/adjudication:

- `table_row_reconstruct(question, evidence_packet)` for contract/verifier
  row-confusion or missing-field diagnostics.
- `chart_binding_check(question, evidence_packet)` for legend/axis/caption
  ambiguity.
- Candidate adjudication only when verifier diagnostics indicate ambiguity:
  current answer, same-row complete-fields answer, and nearby-row/alternate
  series candidate, adjudicated against the contract and cited evidence.

The adjudicator must preserve scorer-shaped concise answers for exact/numeric
questions; several regressions were semantically plausible but shape-wrong.

## Decision

Do not claim progress toward 65% from these runs yet. The implementation
created useful infrastructure and the best clean slice improved to 22/60 on a
hard target/control mix, but every slice still failed the regression gate. Full
n=148 should wait until the repair/adjudication layer shows positive net flips
with <=1 prior-correct control regression on the mixed slice.
