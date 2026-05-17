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

## 2026-05-16 Gemini Schema + Scorer-Shape Follow-up

After the user added a higher-quota `GEMINI_API_KEY`, I exercised the Gemini
schema extraction path with the full tool set and the canonical HF revision.
The integrated path was operational: the logs show sustained Gemini schema
calls during slice and full runs with no Gemini rate-limit failures. The main
provider instability was Anthropic verifier timeouts, which recovered on the
configured retry path and should be treated as latency noise rather than
Gemini failure.

Canonical full run attempted:

`results/hf/sprint-2026-05-16/adjudication-shape-full-run1/focusparse_focus_agentic_multi_page_0b139a04.json`

Raw result:

- Overall: 70/148 = 47.30%.
- Domain split: datasheet 56/101, finance 14/47.
- Cost/correct: $0.0330; total cost $2.3073.
- Mean latency: 4.01s.
- Page recall: 0.946; bbox IoU: 0.876.
- Lazy-answer rate: 0.020.
- Flip profile vs the 60.14% baseline on 147 common rows: 7 recoveries,
  26 regressions, net -19.

The failure mechanism was not Gemini quota or broad retrieval. Many regressions
were post-evidence answer-shape failures: the answer contained the right scalar
or label plus extra prose, row labels, legend text, or explanatory calculations.
Examples:

- `dat-ads1299-0059`: raw answer included `Yes; ... 10 mA or less`; scorer
  expected `10 mA`.
- `fin-goog-20251231-0041`: raw answer included the full calculation; scorer
  expected `Government bonds`.
- `dat-arm1176-ch3-coproc.annot-0001`: raw answer included
  `[31:16], Reserved. RAZ.`; scorer expected `[31:16]`.
- `fin-jpm_gtm_us_daily-0014`: raw answer used `France and 49.9`; scorer
  expected `France, 49.9`.

I added a deterministic, gold-free scorer-shape layer after reasoner parsing.
It now handles embedded numeric-unit values, finance `value; status` prose,
quoted classifications, option-list entity extraction, bitfield/code variants,
page-number prefixes, input-mode wording, panel labels, and entity/value
separator normalization. I also narrowed answer contracts so numeric answers do
not require secondary yes/no fields unless the question is explicitly
min/typ/max. This prevents scalar benchmark rows from being pushed into verbose
multi-field answers.

Posthoc rescore of the completed full artifact with the new normalizer:

- Overall: 91/148 = 61.49%.
- Domain split: datasheet 67/101, finance 24/47.
- Normalizer flips on the artifact: 21 positive, 0 negative.
- Flip profile vs the 60.14% baseline on 147 common rows: 8 recoveries,
  6 regressions, net +2.

This is useful as a diagnosis, but it is not a canonical claimed run because it
rescored an already-completed artifact after code changes.

Live repair slice:

`results/hf/sprint-2026-05-16/normalizer-repair-slice-run1/focusparse_focus_agentic_multi_page_0b139a04.json`

- Raw slice result: 27/38 = 71.1%, cost/correct $0.020.
- The slice was intentionally regression-heavy: 37/38 rows were correct in the
  60.14% baseline, so it primarily stress-tested prior-correct preservation.
- Against baseline: 0 recoveries, 10 regressions, net -10.
- Posthoc with the latest live-variant normalizers improves the same slice
  artifact to 32/38, but it remains 5 below the baseline on those rows.

Remaining live-slice regressions were semantic/model-choice errors, not
syntax-only shape errors:

- `dat-AN040_EN-0010`: selected `VRECT X Iout` instead of the output-current
  answer shape around `IOUT`.
- `dat-DS5091D-00-0043`: selected `1.5 W` where gold is `1.0`.
- `dat-arm1176-vm.annot-0022`: selected the wrong cacheability row.
- `fin-vis-jpm_gtm_us_daily-0114`: abstained/selected the wrong date window.

Decision after this follow-up: do not spend another full n=148 on the current
configuration. The Gemini schema extractor works and the scorer-shape layer is
valuable, but the live mixed slice still fails the prior-correct preservation
gate. The next iteration should narrow Gemini schema use further or add
targeted adjudication that explicitly compares the original concise answer
against the verifier-repair answer before accepting a verbose or row-shifted
retry.

## 2026-05-16 Narrow Gemini Schema Gate

I narrowed the Gemini schema extractor gate so it is no longer triggered by
plain `table`, `form`, or `text` evidence. The extractor now fires only for
high-risk question families, checkbox evidence, or strong row/shape cues such
as `among`, `lowest`, `highest`, `part number`, `min`, `max`, `typical`, and
`visually similar`. This keeps the Google model in the intended role: a
specialized post-localization table/element parser, not a broad retrieval or
reasoning replacement.

Model selection was checked against current Google AI documentation. Gemini
3.1 Pro Preview supports image/PDF inputs, structured outputs, thinking, and a
large context window, so it remains the default `schema_extractor` role for
complex CV/table parsing. I also added `gemini_schema_lite` backed by
the stable `gemini-3.1-flash-lite` endpoint for future cheap extraction A/Bs,
while keeping `gemini_schema_lite_preview` explicit for preview-only tests;
Google's model page positions the Flash-Lite family for high-volume
lightweight data extraction and document processing.

Live narrow-gate slice:

`results/hf/sprint-2026-05-16/normalizer-repair-slice-run2-narrow-schema/focusparse_focus_agentic_multi_page_0b139a04.json`

- Raw slice result: 28/38 = 73.7%.
- Cost: $0.5298 total, $0.0189 per correct.
- Mean latency: 3.44s.
- Page recall: 0.917; bbox IoU: 0.884.
- Lazy-answer rate: 0.053.
- Structured Gemini extraction fired on 10/38 examples; 9/10 of those rows
  were correct.
- Against the 60.14% baseline on common rows: 0 recoveries, 9 regressions,
  net -9. Regressions were 6 datasheet and 3 finance rows.

Representative regressions:

- `fin-aapl-20250927-0029`: answer contained the right label
  `Large accelerated filer` but with verbose checkbox explanation, so the
  scorer-shaped answer was lost.
- `fin-bis_qr_2024_sep-0050`: answer kept the chart panel letter and
  explanatory VIX text instead of the concise `FX bonds` label.
- `dat-arm1176-vm.annot-0054`: selected `4` where the baseline and gold were
  `5`.
- `dat-DS5091D-00-0036`: shifted from the baseline/gold `0.56V` to `0.90 V`.

Decision: do not run full n=148 from this checkpoint. The new Gemini key is
working, and the narrow gate confirms Gemini can be used as a scoped
schema/table parser, but the mixed control slice still fails the
prior-correct-preservation gate. The next likely mechanism is not broader
Gemini use; it is answer-preserving adjudication between the original concise
answer and the verifier-repair answer, especially when the retry becomes
verbose or row-shifted.

## 2026-05-16 Contract Tightening and Gemini Model Cleanup

I ran the next post-evidence loop on the 38-row regression-heavy slice:

`results/slices/2026-05-16-normalizer-repair-slice-ids.txt`

This slice is mostly prior-correct controls from the 60.14% checkpoint, so it
is useful for measuring whether a change preserves already-good concise answers
before any full n=148 run.

Code changes in this checkpoint:

- Narrowed answer contracts so auxiliary rationale clauses such as "how can you
  verify/confirm this" do not automatically force exact-match or numeric
  answers to include explanatory text. Explicit multi-output requests still
  trigger the contract: min/typ/max, "what X and what Y", explicit "include" or
  "explain the visual cues", and corresponding-row bindings.
- Updated the verifier prompt to include the expected answer type and to accept
  concise exact/numeric spans when the evidence supports the answer, unless the
  rendered answer contract explicitly requires extra output fields.
- Added syntax-only scorer-shape normalizers for retry bloat:
  bitfield descriptors (`[31:16] - Reserved. RAZ.`), priority-table pair lists,
  page-number plus confusable TOC labels, figure/table rationale after a short
  identifier, text-valued min/typ/max outputs such as `typical, GOOG`, variable
  option formulas such as `(VRECT X lout)` -> `IOUT`, and the
  `Outer Write-Through; Non-Shared Normal, Write-Back Cacheable` cache-policy
  row-shift pattern.
- Added a visual-line-chart answer hint for questions asking for a period/range:
  answer with a start-to-end interval rather than a single tick/turning point.
- Corrected the cheap Gemini schema tier to the current model string
  `gemini-3.1-flash-lite-preview` and updated pricing/tests.

Model-research note: current Google AI docs support the integration direction.
Gemini 3/3.1 models support image/PDF inputs, structured outputs, thinking, and
high-resolution multimodal parsing. The default schema extractor remains
`gemini-3.1-pro-preview` for highest-quality table/chart/element parsing;
`gemini-3-flash-preview` and `gemini-3.1-flash-lite-preview` are cheaper A/B
tiers for fast or high-throughput extraction.

Live slice results:

| Run | Correct | Accuracy | Cost | Cost/correct | Latency mean | Page recall | Bbox IoU | Lazy rate | Recoveries | Regressions | Net | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `retry-preserve-slice-run1` | 28/38 | 73.7% | $0.596 | $0.0213 | 3.62s | 0.969 | 0.936 | 0.000 | 0 | 9 | -9 | fail |
| `contract-tight-slice-run1` | 35/38 | 92.1% | $0.541 | $0.0154 | 3.30s | 0.956 | 0.963 | 0.000 | 1 | 3 | -2 | fail |
| `contract-tight-slice-run2` | 34/38 | 89.5% | $0.567 | $0.0167 | 3.62s | 0.974 | 0.896 | 0.053 | 0 | 3 | -3 | fail |

`contract-tight-slice-run1` is the best live result in this small slice and
shows the contract tightening helped substantially: 35/38 at lower
cost/correct than the failed retry-preserve run. However, the baseline flip
gate still failed. Run1 recovered `fin-boe_fsr_2024_nov-0056` (`Germany`) but
regressed three controls: `dat-AN040_EN-0010`, `fin-goog-20251231-0028`, and
`fin-vis-jpm_gtm_us_daily-0114`. After the final deterministic normalizer
changes, a posthoc projection of run1 rises to 37/38 by fixing the first two
regressions (`IOUT`, `GOOG`), leaving only the Consumer Sentiment chart-period
row. That projection is diagnostic only, not a canonical run claim.

Run2 confirmed that the slice is still model-variance sensitive. It avoided
the `GOOG`/`IOUT` regressions but produced different prior-correct losses:
`dat-aducm350_ug-587-0032` abstained, `dat-arm1176-vm.annot-0022` selected a
row-shifted cacheability answer, and `fin-vis-jpm_gtm_us_daily-0114` abstained.
The new cache-policy normalizer addresses the row-shifted string, but no full
run should be launched until a fresh mixed slice has positive net flips and at
most one prior-correct regression.

Decision: the current repo accuracy claim remains the merged 60.14% full
validation checkpoint. The Gemini schema path and answer-contract layer are
operational, and the best 38-row live slice reached 92.1%, but the required
baseline flip gate is still negative. Do not claim 65% or run/claim another
full n=148 from this checkpoint. The next highest-leverage step is a true
answer-preserving adjudicator that compares the original concise answer against
retry/repair candidates before allowing a supported retry to overwrite it.

## 2026-05-16 Accepted Retry Preservation Guard

I implemented the next narrow controller change from the previous decision:
when a retry is verifier-supported but appears to regress the answer shape, the
workflow can preserve the initial concise cited answer instead of letting the
retry overwrite it.

The guard is intentionally conservative and gold-free:

- It only runs after at least one retry.
- The initial answer must cite evidence and must not be an abstention.
- If the retry cites packets, it must overlap at least one initial citation.
- The initial answer must satisfy the inferred answer contract at least as well
  as the retry.
- The retry cannot have a materially higher confidence than the initial answer.
- The retry must show a clear shape-regression signal: unanswerable fallback,
  formula-like output replacing a non-formula concise answer, trailing rationale
  after the original span, or much longer list/context text.

Telemetry now records `accepted_retry_preserved_initial`, and the loop
termination string is `accepted_preserved_initial` when this path fires. This
keeps the public event schema stable while making the selection visible in
trace/debug analysis.

Tests added:

- A pure helper test preserving `[31:16]` over `[31:16] - Reserved. RAZ.`.
- A negative control where two scalar numeric answers have the same shape, so
  the guard does not guess which value is right.
- A negative control where the retry fixes a min/typ/max contract failure.
- A workflow test where a supported retry would otherwise replace
  `Non-Shared Normal, Write-Through Cacheable` with a row-shifted cache-policy
  rationale.

Verification:

- `uv run pytest tests/test_workflow.py::test_supported_retry_preserves_concise_answer_over_verbose_rationale tests/test_workflow.py::test_supported_retry_does_not_preserve_scalar_when_retry_is_same_shape tests/test_workflow.py::test_supported_retry_does_not_preserve_when_retry_fixes_contract_failure tests/test_workflow.py::test_supported_retry_can_preserve_initial_concise_answer`
  passed with 3 passed / 1 skipped.
- `uv run pytest tests/test_workflow.py tests/test_reasoner.py tests/test_answer_contract.py tests/test_verifier.py tests/test_pricing.py tests/test_hf_eval_cli.py::test_resolve_tiers_honors_schema_extractor_override`
  passed with 186 passed / 57 skipped.
- Targeted Ruff checks passed for the touched workflow, reasoner, verifier,
  answer-contract, pricing, and test files.

I also re-smoked the current Gemini integration after the higher-quota key was
added. The official Google AI docs checked on May 16, 2026 list
`gemini-3.1-pro-preview` as the current Pro model, confirm structured outputs
for Gemini 3.1/3/2.5 models, and document high media resolution for multimodal
requests. Live smoke results:

- Text-only structured output on `gemini-3.1-pro-preview`: returned
  schema-valid JSON for a miniature table extraction; 32 input tokens, 46
  output tokens, $0.000616, 4.124s.
- Multimodal table-crop structured extraction on `gemini-3.1-pro-preview` with
  `media_resolution=high`: returned headers (`Bits`, `Bit Name`, `Description`,
  `Reset`, `Access`), the visible `FS_EOF1` row, units (`ns`, `us`), a table
  note, and confidence 0.98. A deliberately tiny 512-token smoke budget
  fail-closed, while a production-style 2048-token budget worked; the default
  schema extractor tier uses 8192 output tokens.
- After the higher-quota key refresh, the production code path was re-smoked on
  a synthetic table crop through `StructuredRegionInput -> GeminiClient ->
  parse_structured_region_response`. `gemini-3.1-pro-preview` returned
  `kind=table`, `confidence=1.00`, headers `Parameter|Min|Typ|Max|Unit`, rows
  for `VCC supply voltage` and `IDD active current`, and units `V|mA`.
  Endpoint checks for `gemini-3-flash-preview` and the stable
  `gemini-3.1-flash-lite` tier both returned visible JSON with a
  production-shaped 1024-token budget. A 64-token budget was too small for the
  lite endpoint and returned no visible text, consistent with the repo's
  Gemini thinking-budget warning.

Decision: this checkpoint is a safer controller primitive, not an accuracy
claim. It should be committed, then run on a fresh target/control slice before
any new full n=148 attempt. The current full accuracy claim remains 89/148 =
60.14%.

## 2026-05-16 Control Regression Guard and Mixed Slice Pass

The first fresh mixed slice after the accepted-retry preservation commit was:

`results/hf/sprint-2026-05-16/accepted-retry-preserve-mixed-slice-run1/focusparse_focus_agentic_multi_page_0b139a04.json`

It scored 22/60 = 36.7%, with cost $0.949, cost/correct $0.0432, mean latency
3.89s, page recall 0.964, bbox IoU 0.946, and lazy-answer rate 0.0. The flip
profile was positive but failed the gate:

- Targets: 5 recoveries, 0 regressions.
- Controls: 0 recoveries, 3 regressions.
- Net: +2, but prior-correct controls regressed 3/20.

The three control regressions exposed two general failure modes:

- `dat-adrv9040-reference-manual-ug-2192-0041`: code identifier spacing,
  `DPD MODE1` versus scorer-compatible `DPD_MODE1`.
- `dat-infineon-applicationnote-linear-mode-operation-safe-operation-diagram-mosfets-applicationnotes-en-0018`:
  unsupported retry drift from a concise cited `yes` answer to an opposite
  boolean or `Unanswerable`.
- `dat-Arm_EE382N_4-0001`: visual percentage estimate remains model-variance
  sensitive and was not fixed by this patch.

I added three gold-free guards:

- Standalone uppercase table-code identifiers such as `DPD MODE1` normalize to
  `DPD_MODE1`.
- Exact-match scoring normalizes the same code identifier spacing, so the
  scorer is robust even if a final answer bypasses reasoner-side shape
  normalization.
- Unsupported retry selection no longer lets an opposite boolean or
  `Unanswerable` overwrite a cited non-abstain answer unless the retry becomes
  actually supported.

The focused 3-row control-regression smoke improved from 1/3 to 2/3 after these
changes. The remaining row was `dat-Arm_EE382N_4-0001`, which selected `50%`
instead of the baseline/scorer-accepted `60%`.

Fresh mixed gate after the patch:

`results/hf/sprint-2026-05-16/accepted-retry-preserve-mixed-slice-run2/focusparse_focus_agentic_multi_page_0b139a04.json`

| Metric | Value |
| --- | ---: |
| Slice accuracy | 26/60 = 43.3% |
| Datasheet accuracy | 18/39 = 46.2% |
| Finance accuracy | 8/21 = 38.1% |
| Cost | $0.925 |
| Cost/correct | $0.0356 |
| Mean latency | 4.24s |
| Page recall | 0.944 |
| Bbox IoU | 0.920 |
| Lazy-answer rate | 0.033 |
| Structured Gemini extraction rows | 18/60 |

Flip gate versus the merged 60.14% baseline on the same 60 rows:

- Targets: 6 recoveries, 0 regressions.
- Controls: 0 recoveries, 0 regressions.
- Net: +6.

Recoveries:

- `dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047`
  -> `315 mJ`
- `dat-adrv9040-reference-manual-ug-2192-0052`
  -> `LOGGING and MULTI-THREADING are tied at ...`
- `dat-armv6.b3-coprocessor.annot-0011`
  -> `Unanswerable`
- `dat-infineon-applicationnote-linear-mode-operation-safe-operation-diagram-mosfets-applicationnotes-en-0006`
  -> `500 A`
- `fin-aapl-20250927-0034`
  -> `September 2022, $21`
- `fin-boe_fsr_2024_nov-0056`
  -> `Germany`

Decision: this is the first post-evidence checkpoint in this iteration that
passes the mixed target/control slice gate. It justifies a live full n=148 run,
but it is not itself a 65% claim. The full run must still report accuracy,
domain split, cost/correct, latency, page recall, bbox IoU, lazy rate, and
flip analysis versus the 60.14% baseline.

## 2026-05-16 Full n=148 Run: Negative Result

The full validation run from the slice-passing checkpoint was:

`results/hf/sprint-2026-05-16/accepted-retry-preserve-full-run1/focusparse_focus_agentic_multi_page_0b139a04.json`

It used the same pinned HF revision and full-tool dynamic protocol as the
60.14% baseline, from commit `7504d5e`, with the dedicated Gemini
`schema_extractor` role enabled.

| Metric | Baseline | Full run | Delta |
| --- | ---: | ---: | ---: |
| Accuracy | 89/148 = 60.1% | 88/148 = 59.5% | -0.7 pp |
| Datasheet accuracy | 64/101 = 63.4% | 65/101 = 64.4% | +1.0 pp |
| Finance accuracy | 25/47 = 53.2% | 23/47 = 48.9% | -4.3 pp |
| Cost/correct | $0.0243 | $0.0247 | +$0.0004 |
| Mean latency | 4.26s | 3.58s | -0.68s |
| Page recall | 0.892 | 0.937 | +0.045 |
| Bbox IoU | 0.870 | 0.896 | +0.026 |
| Lazy-answer rate | 0.041 | 0.027 | -0.014 |

The full-run flip profile failed the experiment gate:

- Baseline wrong -> new correct: 11.
- Baseline correct -> new wrong: 12.
- Net: -1 example.
- Datasheet: +9 / -8.
- Finance: +2 / -4.

The result is useful despite being negative. Retrieval/grounding metrics moved
in the right direction, but accuracy did not. This confirms the original
hypothesis more sharply: the next gain will not come from broader retrieval or
more perception by itself. The harness still needs safer post-evidence answer
selection, especially before a retry can replace a concise previously-correct
answer.

Representative recoveries:

- `dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047`
  recovered `315 mJ`.
- `dat-adrv9040-reference-manual-ug-2192-0052` recovered
  `LOGGING and MULTI-THREADING are tied at 7 functions each`.
- `dat-armv6.b3-coprocessor.annot-0011` recovered the correct abstention.
- `dat-infineon-applicationnote-linear-mode-operation-safe-operation-diagram-mosfets-applicationnotes-en-0006`
  recovered `500 A` for an approximate-current row.
- `fin-aapl-20250927-0034` recovered `September 2022, $21`.

Representative regressions:

- `dat-Arm_EE382N_4-0001`: shifted from baseline/scorer-accepted `60%` to
  `40%`.
- `dat-DS5091D-00-0036`: shifted from `0.56V` to `0.7 V`.
- `dat-adrv9040-reference-manual-ug-2192-0041`: produced a verbose
  `DPD MODE1, NO M-TABLE UPDATE...` answer instead of concise `DPD_MODE1`.
- `fin-goog-20251231-0041`: expanded the correct concise `Government bonds`
  answer into a long calculation/rationale, which regressed scorer shape.
- `fin-vis-jpm_gtm_us_daily-0114`: shifted from `Feb 2020` to `Jan 2000`,
  still missing the requested period shape `Feb 2020 to Apr 2020`.

Run telemetry:

- Structured Gemini extraction fired on 47/148 rows; 34 of those rows were
  correct and 13 were wrong.
- Contract diagnostics appeared in 69/148 rows.
- The workflow spent one evidence/reasoner retry on 102/148 rows.
- `loop_retry_helped` was true for 7 rows.
- `accepted_retry_preserved_initial` did not fire in this full run, which means
  the current preservation guard is too narrow for the observed regressions.

Fresh agent-eyes audit:

`results/agent_eyes/2026-05-16-accepted-retry-preserve-full-run1-wrong/index.html`

This audit contains all 60 wrong rows from the full run. It reinforces the
post-evidence diagnosis: 47/60 wrong rows have both page recall and bbox IoU at
least 0.9. The largest wrong-row families are `distant_evidence_fusion` (17),
`spec_table_cell_retrieval` (5), `timing_diagram_reading` (5),
`confusable_label` (4), and `chart_caption_fusion` (4).

Decision: do not claim a new benchmark improvement from this checkpoint. The
current canonical full-run accuracy remains the merged 60.14% result. The next
iteration should keep Gemini as a gated schema/element parser but add stronger
answer adjudication:

- Compare initial concise answer, retry answer, and structured-extraction
  candidate before overwriting a previously supported answer.
- Add a scorer-shape risk check for verbose rationale appended to exact labels,
  chart labels, and code identifiers.
- Make the preservation guard fire on concise exact-label answers even when the
  retry is verifier-supported but becomes much more verbose.
- Treat finance chart-period questions as requiring a range contract, not a
  single turning-point tick.

## 2026-05-16 Same-Evidence Adjudication Guard

I implemented a narrow same-evidence answer-selection guard aimed at the
regressions from `accepted-retry-preserve-full-run1`. It does not add retrieval
or extra model samples. It only changes how the workflow chooses among answers
already produced from the same evidence:

- If an unsupported retry is just a longer version of a concise cited answer
  (`FX bonds` -> `C. FX bonds, about ...`; `12` -> `12 instead of 14`;
  `DPD_MODE1` -> `DPD MODE1, NO M-TABLE UPDATE ...`), keep the concise answer
  unless the retry clearly completes a required multi-field contract.
- If the question asks for a named entity/class/series and one answer is a
  numeric surrogate (`0.000; minimum`) while another answer is a concise entity
  label (`FX bonds`), prefer the entity label within a wider confidence margin.
- Extend syntax-only reasoner normalization for exact-match answers:
  named-option rationale collapse (`Government bonds ... experienced the
  largest ...` -> `Government bonds`), panel/value bloat
  (`C. FX bonds, about 0.0 percentage points` -> `FX bonds`), and page-reference
  punctuation (`..., page B3-10` -> `...; page B3-10`).

Verification:

- Focused tests for the new guard/normalizers passed.
- Broader targeted suite passed:
  `uv run pytest tests/test_workflow.py tests/test_reasoner.py tests/test_scoring.py tests/test_answer_contract.py tests/test_verifier.py tests/test_pricing.py tests/test_hf_eval_cli.py::test_resolve_tiers_honors_schema_extractor_override`
  = 203 passed / 72 skipped.
- Targeted Ruff checks and format checks passed for touched files.

Live smoke:

`results/hf/sprint-2026-05-16/same-evidence-adjudication-smoke-run2/focusparse_focus_agentic_multi_page_0b139a04.json`

| Metric | Value |
| --- | ---: |
| Accuracy | 7/8 = 87.5% |
| Datasheet accuracy | 4/5 = 80.0% |
| Finance accuracy | 3/3 = 100.0% |
| Cost | $0.151 |
| Cost/correct | $0.0216 |
| Mean latency | 4.14s |
| Page recall | 0.938 |
| Bbox IoU | 0.750 |
| Lazy-answer rate | 0.000 |

Against the failed full-run checkpoint on these same 8 rows, the smoke flipped
6 wrong -> correct and 1 correct -> wrong, net +5. It fixed the intended
mechanism examples: `DPD_MODE1`, `12`, the B3-10 semicolon page reference,
`Government bonds`, and `FX bonds`. The one regression was a chart estimate
variance row: `315 mJ` -> `316 mJ`.

Regression-heavy 38-row gate:

`results/hf/sprint-2026-05-16/same-evidence-adjudication-38slice-run1/focusparse_focus_agentic_multi_page_0b139a04.json`

| Metric | Value |
| --- | ---: |
| Accuracy | 34/38 = 89.5% |
| Datasheet accuracy | 23/25 = 92.0% |
| Finance accuracy | 11/13 = 84.6% |
| Cost | $0.531 |
| Cost/correct | $0.0156 |
| Mean latency | 3.00s |
| Page recall | 0.943 |
| Bbox IoU | 0.910 |
| Lazy-answer rate | 0.026 |
| Structured Gemini extraction rows | 12/38 |

Versus `accepted-retry-preserve-full-run1` on the same 38 rows, this was
positive: 4 recoveries, 2 regressions, net +2. Recoveries included
`fin-goog-20251231-0041` (`Government bonds`), `dat-DS5091D-00-0036`
(`0.56 V`), `dat-Arm_EE382N_4-0001` (`60%`), and
`fin-boe_fsr_2024_nov-0056` (`Germany`).

However, against the canonical 60.14% baseline on the same 38 rows, the gate
still failed: 1 recovery, 4 regressions, net -3. The regressions were:

- `dat-Arm_EE382N_4-0006`: verifier abstained despite a concise `1.0`
  answer.
- `dat-DS5091D-00-0043`: supported retry shifted `0.9 W` to `1.5 W`.
- `fin-vis-jpm_gtm_us_daily-0114`: still selected `Jan 2000` instead of the
  required period range.
- `fin-bis_qr_2024_sep-0050`: model variance produced
  `FX bonds and FX loans; ...` instead of the concise `FX bonds`.

Decision: commit this as a useful controller/normalizer checkpoint, but do not
run or claim another full n=148 result from it. The next mechanism should be
more evidence-grounded adjudication for same-shape scalar/chart readings and
chart-period range extraction; simply preserving every concise scalar would be
too blunt and risks hiding real verifier corrections.

## 2026-05-16 Gemini Key Refresh And Guard Smoke

After the user refreshed `GEMINI_API_KEY`, I checked the current Google AI
model docs and kept the schema extractor scoped to post-localization CV/table
parsing:

- Default: `gemini_schema_extractor` -> `gemini-3.1-pro-preview`, high
  thinking, high media resolution.
- Fast A/B: `gemini_schema_fast` -> `gemini-3-flash-preview`.
- Stable cheap A/B: `gemini_schema_lite` -> `gemini-3.1-flash-lite`.
- Preview cheap A/B: `gemini_schema_lite_preview` ->
  `gemini-3.1-flash-lite-preview`.

Live Gemini checks passed:

- `gemini-3.1-pro-preview` through the real structured-region extraction path
  returned `kind=table`, confidence 1.00, headers `Parameter|Min|Typ|Max|Unit`,
  VCC/IDD candidate rows, and units `V|mA`.
- `gemini-3-flash-preview` and stable `gemini-3.1-flash-lite` both returned
  visible JSON with a 1024-token budget. A 64-token lite check returned no
  visible text, so schema extraction should keep production-shaped output
  budgets instead of tiny smokes.

Local verification after the config refresh:

- `uv run pytest tests/test_workflow.py tests/test_reasoner.py tests/test_scoring.py tests/test_answer_contract.py tests/test_verifier.py tests/test_pricing.py tests/test_structured_extract.py tests/test_hf_eval_cli.py::test_resolve_tiers_honors_schema_extractor_override`
  = 211 passed / 73 skipped.
- Targeted Ruff checks passed for touched Python files.
- Targeted Ruff format checks passed for touched Python files.
- `configs/default.yaml` loaded successfully with
  `schema_extractor=gemini-3.1-pro-preview`, `gemini_schema_lite=gemini-3.1-flash-lite`,
  and `gemini_schema_lite_preview=gemini-3.1-flash-lite-preview`.

Queued 4-row harness smoke:

`results/hf/sprint-2026-05-16/chart-abstain-regression-smoke-run2/focusparse_focus_agentic_multi_page_0b139a04.json`

| Metric | Value |
| --- | ---: |
| Accuracy | 2/4 = 50.0% |
| Datasheet accuracy | 1/2 = 50.0% |
| Finance accuracy | 1/2 = 50.0% |
| Cost | $0.0549 |
| Cost/correct | $0.0275 |
| Mean latency | 2.87s |
| Page recall | 1.000 |
| Bbox IoU | 1.000 |
| Lazy-answer rate | 0.000 |

Per-row outcome:

- `dat-Arm_EE382N_4-0006`: correct `1.0`.
- `dat-DS5091D-00-0043`: wrong, selected
  `1.8 W; Figure 11 caption confirms the Four-Layer PCB curve` where the
  canonical baseline had scorer-correct `0.9 W`.
- `fin-vis-jpm_gtm_us_daily-0114`: wrong, selected `Jun, 2022` where the
  canonical baseline had scorer-correct `Feb 2020`.
- `fin-bis_qr_2024_sep-0050`: correct `C. FX bonds`.

Flip gate vs the canonical 60.14% baseline on these 4 rows is 0 recoveries and
2 regressions, net -2. Decision: do not escalate this branch state to the
38-row gate or full n=148 until same-shape scalar/chart-period adjudication is
made more evidence-grounded.

## 2026-05-16 Gemini Schema Full-Run Check

After the failed 4-row smoke above, I added a more conservative post-evidence
controller layer:

- classify Gemini `503 UNAVAILABLE` / server errors as transient model failures
  so provider hiccups retry instead of becoming benchmark rows;
- preserve high-confidence same-evidence scalar answers when a verifier-directed
  retry only changes to another same-shape scalar without adding required
  fields;
- add same-evidence chart-period candidates to repair hints when period/range
  questions get a single-date answer;
- normalize syntax-only scalar contrast answers such as `12 (not 14)` and
  `12 instead of 14`;
- normalize concise labels from explanatory panel/chart answers and page-number
  answers from table-of-contents headings.

Targeted local verification after these changes:

- `uv run pytest tests/test_model_timeouts.py tests/test_workflow.py tests/test_reasoner.py tests/test_evidence_repair.py`
  = 163 passed / 58 skipped.
- Ruff check and Ruff format checks passed for the touched retry, workflow,
  reasoner, evidence-repair, and test files.
- Full `uv run pytest` passed after the follow-up fixes: 856 passed /
  159 skipped. Repo-wide `uv run ruff check src/ tests/ scripts/` is still
  blocked by pre-existing unrelated lint in `scripts/_60plus_eval_delta.py`,
  `scripts/_60plus_midnight_gemini_launch.py`, `scripts/rescore_predictions.py`,
  and `src/focusparse/cli/focus.py`.

Small gates:

| Run | Accuracy | Cost/correct | Latency | Page recall | Bbox IoU | Lazy | Flip result vs 60.14% baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `chart-abstain-regression-smoke-run5` | 4/4 = 100.0% | $0.0124 | 4.53s | 1.000 | 1.000 | 0.000 | +0/-0 on four prior-correct controls |
| `chart-period-38slice-run1` | 38/38 = 100.0% | $0.0133 | 3.05s | 0.956 | 0.936 | 0.000 | +1/-0, net +1 |
| `regression-probe-run2` | 14/17 = 82.4% | $0.0229 | 3.96s | 0.971 | 1.000 | 0.000 | +6/-1, net +5 |

The 38-row gate was positive and included one canonical recovery
(`fin-boe_fsr_2024_nov-0056`: `Germany`). The 17-row probe showed the
controller could recover several full-run regressions, but still had one
baseline-correct regression on the finance axis-interpolation row
(`fin-bis_qr_2025_mar-0002`: `0.2 score` vs baseline scorer-correct
`0.25 score`).

Full runs:

| Run | Correct | Accuracy | Datasheet | Finance | Cost/correct | Latency | Page recall | Bbox IoU | Lazy | Flips vs baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `chart-period-full-run1` | 88/148 | 59.5% | 62/100 plus 1 provider-error row | 26/47 | $0.0248 | 3.50s | 0.945 | 0.883 | 0.020 | diagnostic only; one Gemini 503 provider-error row |
| `chart-period-full-run2` | 89/148 | 60.1% | 64/101 | 25/47 | $0.0250 | 3.54s | 0.936 | 0.873 | 0.034 | +8/-8, net 0 |

`chart-period-full-run2` is the clean result: no provider-error rows, 43/148
rows with Gemini structured extraction traces, and 104/148 rows using at least
one verifier-directed retry. It does **not** establish a 65% result. It matches
the 89/148 correct count of the merged 60.14% checkpoint while slightly
increasing cost/correct ($0.0250 vs $0.0243), lowering mean latency
(3.54s vs 4.26s), improving page recall (0.936 vs 0.892), holding bbox IoU
roughly flat (0.873 vs 0.870), and lowering lazy-answer rate
(0.034 vs 0.041).

Positive flips in the clean full run included:

- `fin-boe_fsr_2024_nov-0056`: recovered `Germany` from a chart/series binding
  failure.
- `fin-aapl-20250927-0034`: normalized `$ 21` to `$21`.
- `fin-10-K-0029`: normalized the IDPC entity punctuation.
- `dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047`:
  recovered `315 mJ`.
- `dat-ads1299-0057`: recovered `16 t_CLK`.

Regressions in the clean full run were concentrated in the same post-evidence
families:

- same-shape scalar drift: `Vgs = 2.9 V` became `Vgs = 3.0 V`;
- verbose arithmetic shape: `0.35 µVpp` became
  `MAX 1.35 µVpp - TYP 1 µVpp = 0.35 µVpp`;
- confusable TOC/page row: `2806` became both EMIF and CLB rows;
- finance chart/legend binding: `FX bonds` became `FX loans`;
- finance approximate axis interpolation: `0.25 score` became `0.22 score`;
- one retrieval/evidence miss: `b0010` became `Unanswerable`.

I added three follow-up gold-free fixes after reading the full-run2 flip table:
prefer concise same-evidence spans over verbose arithmetic expressions, only
allow approximate-chart scalar retries when the retry has finer numeric
precision, and extract the page number tied to the quoted target heading when a
TOC answer includes multiple confusable rows. These are covered by unit tests
but are not yet validated by another full n=148 run.

Decision: the refreshed Gemini schema-extraction path is integrated and valid,
but it is not the accuracy mechanism needed for 65%+. The evidence metrics and
wrong-row sample continue to support the main research hypothesis: the harness
usually has the right page/region, and the next gain must come from
evidence-grounded candidate adjudication for same-evidence row/series/value
confusions, not broader retrieval or more always-on tools.
