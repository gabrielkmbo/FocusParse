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

## Slice Results

| Run | Correct | Accuracy | Cost | Cost/correct | Latency mean | Page recall | Bbox IoU | Lazy rate | Recoveries | Regressions | Net | Control regressions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| contract guard | 17/60 | 28.3% | $0.843 | $0.050 | 4.43s | 0.942 | 0.934 | 0.017 | 3 | 6 | -3 | 6 |
| evidence groups | 16/60 | 26.7% | $0.827 | $0.052 | 4.08s | 0.903 | 0.835 | 0.067 | 3 | 7 | -4 | 7 |
| hybrid groups + packets | 19/60 | 31.7% | $0.905 | $0.048 | 4.14s | 0.931 | 0.911 | 0.033 | 6 | 7 | -1 | 7 |

None passed the mixed-slice gate, so I did not run a full n=148 validation run
from these checkpoints.

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

## Interpretation

The core hypothesis was right in direction but incomplete in mechanism:
post-evidence packaging and contracts do recover high-recall/high-IoU failures,
especially label-vs-value and multi-field rows. However, prompt-only grouping
also increases answer verbosity, over-abstention, and OCR-looking span drift on
previously correct controls.

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
created useful infrastructure, but all three slices failed the regression gate.
Full n=148 should wait until the repair/adjudication layer shows positive net
flips with <=1 prior-correct control regression on the mixed slice.
