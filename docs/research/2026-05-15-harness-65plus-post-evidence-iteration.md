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

Commit `72b41f9`: made eval runs fail fast on provider throttle/quota
failures instead of converting those rows into benchmark failures. Daily quota
exhaustion is no longer retried as a transient model error. This is a validity
guard, not an accuracy mechanism: it prevents contaminated slice/full-run
artifacts after provider quota is exhausted.

This checkpoint adds targeted same-evidence repair hints for verifier-directed
reasoner retries. The hint includes the previous answer/citations and converts
diagnostics into concrete repair instructions: multi-field completion,
label-vs-value extraction, corresponding-row/table-row candidate adjudication,
checkbox nearest-label binding, and chart legend/series/panel/axis binding.
It also adds an internal same-evidence repair worksheet with Candidate A/B/C
slots: previous answer, same-row/series/label-completed answer, and nearby
confusable row/series/checkbox binding. This implements the first adjudication
layer without adding broad retrieval or generic self-consistency.

Current implementation checkpoint: verifier-directed retries now also receive
deterministic repair context built from the same `EvidencePacket` list already
available to the reasoner. For row/multi-field/label-value/checkbox failures,
the context surfaces compact candidate rows/lines from the cited packets,
filtering out generic weak matches such as unrelated `net sales` rows when the
question has stronger cues like `Products` and `Gross margin`. For chart
legend-binding failures, it surfaces chart CSV plus legend, axis, caption,
panel, and footnote lines. This is still gold-free and same-evidence only: it
does not run broader retrieval, force `chart_to_table`, or add example-id
logic. The expected mechanism is lower verifier false-accept/regression risk
when a retry is already justified by contract diagnostics; the next evidence
gate remains the mixed 60-row slice before any full n=148 run.

Verification for this checkpoint: focused repair/workflow tests passed, targeted
Ruff checks and format checks passed for the changed files, and full
`uv run pytest` passed with 788 passed / 156 skipped. Full repo-wide Ruff
checks remain blocked by pre-existing unrelated lint/format issues in files
outside this patch, so they are not evidence against this specific change.

Gemini schema-extraction checkpoint: after reviewing the current Gemini docs, I
added a dedicated `schema_extractor` role rather than changing the global
planner/reasoner/verifier tiers. The role uses `gemini-3.1-pro-preview` with
`thinking_level=high` and `media_resolution=high`; `gemini_schema_fast`
(`gemini-3-flash-preview`) is available as an opt-in lower-cost A/B tier via
`FOCUSPARSE_TIER_SCHEMA_EXTRACTOR=gemini_schema_fast`. The research basis:
Google now identifies Gemini 3.1 Pro as the migration target after Gemini 3 Pro
Preview shutdown, Gemini document understanding explicitly covers charts and
tables plus structured extraction, Gemini 3 supports structured JSON outputs,
and high media resolution is recommended when extra visual detail is worth the
latency/cost tradeoff.

Implementation details:

- `GeminiClient` now supports `thinking_level`, `media_resolution`, and native
  JSON response schemas when the backend is Gemini.
- `chart_to_table` now receives the `schema_extractor` client instead of the
  reranker tier, so chart CSV extraction can use Gemini 3.1 Pro while remaining
  gated by existing chart-family/region checks.
- Added `tools/structured_extract.py`, a fail-closed table/form/text schema
  extractor. It asks Gemini for compact headers, units, candidate rows,
  key-values, checkboxes, and notes, then appends a concise
  `Gemini structured extraction` note to the packet OCR channel. Public
  `EvidencePacket`/event schemas are unchanged.
- The structured extractor is gated to table/form/text/checkbox-like regions,
  table/confusable/field-shaped question families or cues, and at most the top
  two inspected packets per example.
- Updated pricing for Gemini 3.1 Pro / Gemini 3 Flash list prices used by this
  path. A live smoke against a cached datasheet page succeeded:
  `gemini-3.1-pro-preview` produced a table schema for digital output pin rows
  with `confidence=0.95`; a raw image smoke cost about `$0.0053` for 1,136 input
  and 252 output tokens. This is not a benchmark result, only an integration
  validity check.

Workflow smoke after this checkpoint:
`results/hf/sprint-2026-05-15/gemini-schema-extractor-smoke-run1/focusparse_focus_agentic_multi_page_0b139a04.json`
ran the existing 3-row smoke slice with the default planner/router tiers and
the new `schema_extractor` role. It scored 2/3 = 66.7%, cost `$0.0472`
total / `$0.0236` per correct, mean latency 3.63s, page recall 0.833, bbox IoU
0.881, and lazy rate 0.0. The trace confirms `Gemini structured extraction`
notes were injected for form/checkbox packets. This proves the integrated path
runs with the updated key, but it is not evidence of a benchmark gain: the
Apple gross-margin row still failed by returning a verbose shape-wrong answer
instead of `180,683; typical`. The next valid gate remains the 60-row mixed
target/control slice.

Follow-up commits `cf444c7` and `14075d5` tightened syntax-only normalization
and contract severity after Gemini exposed two post-evidence shape issues.
Finance exact-match answers now normalize verbose corresponding-value/status
phrases and simple `value, status` outputs such as `$ 180,683, typical` to
`180,683; typical`. Datasheet exact-match answers now normalize firmware
file/size pairs such as `ADRV9040_FW.bin; 641 kb` to
`ADRV9040_FW.bin, 641 kb`, and structured file/size pairs no longer trigger a
severe visual-explanation contract failure merely because the question asks for
supporting context. These rules are gold-free syntax rules, not example-id
rules.

Two targeted live checks validated those mechanisms:

- `gemini-contract-normalizer-smoke-run2`: 3/3 = 100.0%, cost/correct
  `$0.0171`, mean latency 4.51s, page recall 0.833, bbox IoU 0.881, lazy rate
  0.0. It fixed the Apple gross-margin shape to `180,683; typical`.
- `file-size-regression-smoke-run1`: 1/1 = 100.0%, cost/correct `$0.0167`,
  mean latency 4.21s. It fixed the datasheet firmware control to
  `ADRV9040_FW.bin, 641 kb`.

## Slice Results

| Run | Correct | Accuracy | Cost | Cost/correct | Latency mean | Page recall | Bbox IoU | Lazy rate | Recoveries | Regressions | Net | Control regressions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| contract guard | 17/60 | 28.3% | $0.843 | $0.050 | 4.43s | 0.942 | 0.934 | 0.017 | 3 | 6 | -3 | 6 |
| evidence groups | 16/60 | 26.7% | $0.827 | $0.052 | 4.08s | 0.903 | 0.835 | 0.067 | 3 | 7 | -4 | 7 |
| hybrid groups + packets | 19/60 | 31.7% | $0.905 | $0.048 | 4.14s | 0.931 | 0.911 | 0.033 | 6 | 7 | -1 | 7 |
| answer-shape guard minifacts run1 | 22/60 | 36.7% | $0.851 | $0.039 | 3.95s | 0.961 | 0.900 | 0.017 | 4 | 2 | +2 | 2 |
| leading identifier minifacts run2 | 20/60 | 33.3% | $0.848 | $0.042 | 4.09s | 0.978 | 0.933 | 0.000 | 3 | 3 | 0 | 3 |
| Gemini schema + contracts slice run1 | 22/60 | 36.7% | $0.963 | $0.044 | 3.75s | 0.967 | 0.951 | 0.017 | 4 | 2 | +2 | 2 |
| Gemini schema + contracts slice run2 | 22/60 | 36.7% | $0.992 | $0.045 | 6.71s | 0.944 | 0.900 | 0.033 | 4 | 2 | +2 | 2 |
| finance adjudication slice run1 | 23/60 | 38.3% | $0.939 | $0.041 | 3.66s | 0.975 | 0.949 | 0.000 | 5 | 2 | +3 | 2 |
| finance adjudication + shape smoke | 2/2 | 100.0% | $0.028 | $0.014 | 3.88s | 1.000 | 1.000 | 0.000 | n/a | n/a | n/a | n/a |
| finance adjudication slice run2 | 22/60 | 36.7% | $0.921 | $0.042 | 3.56s | 0.953 | 0.890 | 0.017 | 4 | 2 | +2 | 2 |

The first disk-light answer-shape run was the best clean slice so far, but it
still failed the mixed-slice gate because prior-correct control regressions
were 2, above the <=1 threshold. A follow-up run after the leading identifier
patch was worse (net 0, 3 control regressions), showing that the remaining
control failures are not only deterministic shape normalization issues.

The Gemini schema runs also failed the gate. They kept a positive net flip
count (+2) and improved evidence metrics on the hard slice, but both runs had
two prior-correct regressions. Run1 regressed `fin-10-K-0033` to
`Unanswerable` and over-completed `dat-adrv9040-reference-manual-ug-2192-0032`;
the file/size normalizer fixed the datasheet regression in a 1-row smoke.
Run2 still had two finance regressions: `fin-aapl-20250927-0002` flipped from
`180,683; typical` to wrong-row `169,148; minimum`, and `fin-10-K-0033`
again abstained despite an initial correct `0.53` answer in the prior slice
trace. This means the next bottleneck is finance row/calculation verifier
adjudication, not raw schema extraction.

The deterministic finance adjudicator fixed two verifier false-reject families
in focused smoke: `fin-aapl-20250927-0002` normalized to `180,683; typical`,
and `fin-10-K-0033` normalized to `0.53` from the same evidence packets. The
first 60-row slice with this path reached the best hard-slice result so far
(`23/60`, net +3), but still had two prior-correct regressions:
`fin-aapl-20250927-0002` became a verbose but semantically right shape
(`September 28, 2024: Gross margin $180,683 -- typical...`) and
`dat-adrv9040-reference-manual-ug-2192-0032` appended an explanation after the
correct file/size pair.

I added two syntax-only normalizers for those regressions: one collapses a
single inline finance value/status pair to `value; status`; the other strips
explanatory prose after a datasheet `file, size` pair. A two-row regression
smoke then scored 2/2 with no retries. However, the follow-up 60-row slice
still failed the gate at `22/60`, net +2, because different control rows
regressed (`dat-Arm_EE382N_4-0001`: `50%` vs gold `70%`; `fin-10-K-0036`:
`96%` vs gold `68%`). That makes the current gain non-reproducible enough to
block a full n=148 run.

One earlier disk-light attempt was discarded as invalid: it hit an Anthropic
429 rate-limit error mid-run and the harness converted affected rows to error
records. Those rows are not counted as evidence for accuracy or flips.

A row-binding slice attempt after commit `71df0b1` was stopped before result
artifacts were written because the planner hit Gemini free-tier daily quota
(`gemini-2.5-flash`, 20 requests/day) and began producing provider-error rows.
It is not counted as evidence. Re-run the same 60-row slice once quota is
available or the planner tier is moved to a non-quota-blocked provider.

After the targeted repair-hint checkpoint, I ran a diagnostic-only 3-row smoke
with `FOCUSPARSE_TIER_PLANNER=cheap_oai` and
`FOCUSPARSE_TIER_ROUTER=cheap_oai` to avoid the exhausted Gemini quota:

`results/hf/sprint-2026-05-15/row-binding-repair-smoke-cheap-oai/`

It scored 3/3 with cost/correct $0.0146, mean latency 3.40s, page recall 1.0,
bbox IoU 1.0, and lazy-answer rate 0.0 on:

- `fin-aapl-20250927-0002`: `180,683; typical`
- `fin-aapl-20250927-0010`: `yes`
- `dat-adrv9040-reference-manual-ug-2192-0041`: `DPD_MODE1`

This is not a canonical slice or full-run claim because planner/router tiers
changed and all three rows were already correct in the 60.14% baseline. It is
only a sanity check that the new repair path runs cleanly on the targeted
failure families without immediate regressions on those controls.

Next canonical gate command, once Gemini planner quota is available again:

```bash
set -a
source /Users/gabrielbo/projects/FocusParse/.env
set +a
export FOCUSPARSE_MODEL_RETRY_ATTEMPTS=2
export FOCUSPARSE_MODEL_RETRY_SLEEP_S=1
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --output-dir results/hf/sprint-2026-05-15/repair-worksheet-slice-run1 \
  --example-ids-file results/slices/2026-05-15-contract-guard-target-control-ids.txt \
  --tool-set full \
  --minimal-artifacts \
  --max-evidence-retries 1
```

Do not set `FOCUSPARSE_TIER_PLANNER` or `FOCUSPARSE_TIER_ROUTER` for the
canonical gate; the 3-row smoke used `cheap_oai` only to bypass an exhausted
quota and is therefore diagnostic-only.

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
- `fin-10-K-0033`: baseline `0.53` regressed to `Unanswerable` in both Gemini
  schema slice runs. In run1, the reasoner initially answered `0.53` with
  citations, but the verifier abstained on the multi-region calculation.

## Interpretation

The core hypothesis was right in direction but incomplete in mechanism:
post-evidence packaging, contracts, and Gemini schema extraction do recover
some high-recall/high-IoU failures, especially label-vs-value and multi-field
rows. However, prompt/schema augmentation alone also increases answer
verbosity, over-abstention, wrong-row selection, and cost/latency on previously
correct controls.

The best clean slices now show positive net flips (+2 to +3), which is
encouraging, but the control-regression gate still blocks a full n=148 run. The
remaining regressions are a mix of finance wrong-row / calculation-verifier
decisions and visual proportion mistakes, not syntax-only shape mistakes. Gemini
3.1 Pro works technically with the new key as a gated schema extractor for
table/chart/element packets, but the current broad schema path is not yet a
reproducible cost-effective accuracy mechanism.

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
created useful infrastructure and the best clean slice improved to 23/60 on a
hard target/control mix, but every 60-row slice still failed the regression
gate. Full n=148 should wait until finance row/calculation adjudication or
tighter Gemini schema gating shows positive net flips with <=1 prior-correct
control regression on the mixed slice.
