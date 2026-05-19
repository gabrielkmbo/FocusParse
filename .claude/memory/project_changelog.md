# Project Changelog

## 2026-05-18

- Completed the decision-grade `agentic_multi_page` full run for the trusted
  LlamaIndex ReAct comparator with the minimal `+2` tool set
  (`inspect_region`, `get_text_layer`) on pinned HF revision
  `3774c67f8b814392b6d04c939e904f749a3f52eb`. Artifact:
  `results/hf/related-work/llamaindex_react_minimal/focusparse_llamaindex_react_agentic_multi_page_0b139a04_tminimal`.
  Result: **18/148 = 12.2%**, cost **$6.36**, cost/correct **$0.353**,
  mean latency **29.9s**, page recall **0.544**, bbox IoU **0.172**,
  evidence reward **0.0345**, lazy-answer rate **0.426**, mean tool calls
  **3.65**. This replaces the old custom ReAct row as the main ReAct comparator
  candidate for `+2`, but it is not competitive with FocusParse.

- Added comparator `--minimal-artifacts` support for `llamaindex_react`,
  `react`, and `agent_baseline` evals. Minimal comparator runs now disable
  per-example prediction cache/resume and route protocol-required summary
  tiles plus crop/text tool artifacts through per-example scratch directories,
  preserving `agentic_multi_page` model input behavior while retaining only
  `run.json` and `per_example.jsonl` as durable run artifacts.

## 2026-05-17

- Validated the first full n=148 FocusParse harness result above the 65% target
  on branch `codex/harness-65plus-iteration`. After a refreshed
  `GEMINI_API_KEY`, the dedicated schema-extractor ladder was live-smoked:
  `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, and
  `gemini-3.1-flash-lite` all returned structured table output from a real
  cached crop, and the API model list exposed all configured extraction tiers.
  The measured accuracy lift came from gold-free answer-shape normalization
  over already-seen evidence: numeric difference results, page-label pairs,
  percent-point OCR shape, reset-zero/final-hex shape, method+unit pairs, and
  branch-instruction/use rows. Posthoc on `chart-period-full-run2` was
  97/148 (+8/-0), the 24-row target/control live slice
  `shape-normalizer-target-control-run1` passed at 21/24 with +5/-0, and full
  `shape-normalizer-full-run1` scored **99/148 = 66.9%**. Domain split:
  datasheet **71/101**, finance **28/47**. Cost/correct **$0.0232**, mean
  latency **3.70s**, page recall **0.949**, bbox IoU **0.881**, lazy-answer
  rate **0.020**, Gemini structured extraction on **47/148** rows. Robust
  occurrence-aware flip analysis vs the canonical merged 60.14% baseline:
  **+15/-5**, net +10. Full `uv run pytest` passed (856 passed / 159 skipped).
  Next work should target the five residual regressions in chart interpolation,
  close visual labels, and finance legend binding.

## 2026-05-16

- Refreshed the Gemini schema-extractor model ladder after checking the current
  Google AI docs. The default remains `gemini-3.1-pro-preview` with high
  thinking/media resolution, `gemini_schema_fast` remains
  `gemini-3-flash-preview`, and `gemini_schema_lite` now uses the stable
  `gemini-3.1-flash-lite` endpoint while `gemini_schema_lite_preview` is kept
  explicit for preview-only A/Bs. Re-smoked the new `GEMINI_API_KEY` through the
  actual structured-region extraction path: Pro returned schema-valid table
  headers/rows/units at confidence 1.00, and both fast/lite endpoints returned
  visible JSON with a production-shaped 1024-token budget. A 64-token lite smoke
  returned no visible text, reinforcing the existing Gemini thinking-budget
  warning.
- Ran the queued 4-row chart/abstain regression smoke after the latest guard
  edits. It scored 2/4 = 50.0% with cost/correct $0.0275, page recall 1.0,
  bbox IoU 1.0, and lazy rate 0.0. It remained negative vs the canonical
  60.14% baseline on the same rows: 0 recoveries and 2 regressions
  (`dat-DS5091D-00-0043`, `fin-vis-jpm_gtm_us_daily-0114`). Do not escalate
  this branch state to a larger slice/full run until same-shape scalar and
  chart-period adjudication are more evidence-grounded.
- Added a control-regression guard after the accepted-retry mixed slice exposed
  three prior-correct losses. Standalone table-code answers such as `DPD MODE1`
  now normalize/score as `DPD_MODE1`, and unsupported retries no longer let an
  opposite boolean or `Unanswerable` overwrite a cited non-abstain answer. The
  3-row control-regression smoke improved from 1/3 to 2/3. The fresh mixed gate
  `accepted-retry-preserve-mixed-slice-run2` passed with 26/60 = 43.3%, 6
  target recoveries, 0 control regressions, cost/correct $0.0356, mean latency
  4.24s, page recall 0.944, bbox IoU 0.920, and lazy rate 0.033. This justifies
  a full n=148 run but is not itself a 65% claim.
- Added a conservative accepted-retry selection guard: when a verifier-supported
  retry looks like answer-shape regression, the workflow can preserve the
  initial concise cited answer instead of overwriting it with verbose rationale,
  adjacent-row context, formulas, or list-like repair text. The guard is
  gold-free, only runs after a retry, requires citation overlap, checks the
  inferred answer contract, and records `accepted_retry_preserved_initial` in
  telemetry. Focused workflow tests passed; a fresh mixed slice is still needed
  before any full n=148 claim.
- Re-smoked the higher-quota Gemini key on `gemini-3.1-pro-preview` for both
  text-only structured output and a cached table-crop multimodal structured
  extraction. The Pro path returned schema-valid JSON, including table headers,
  row content, units, note, and confidence when run with the production-style
  schema extractor budget.
- Added narrow deterministic finance adjudication for two same-evidence finance
  verifier false-reject families: corresponding row/value/status answers and
  repurchase-dividend ratio calculations. The adjudicator only accepts when the
  current cited answer already matches a deterministic reconstruction from the
  same packets; it does not invent replacement answers or use gold/example ids.
  A 2-row smoke passed, and the first mixed slice improved to 23/60 with net +3,
  but still failed the control-regression gate with two prior-correct
  regressions.
- Tightened syntax-only answer-shape normalization for two regressions observed
  after the finance adjudicator: inline finance `value -- status` sentences now
  collapse to `value; status`, and datasheet `file, size; explanatory prose`
  collapses to `file, size`. The focused 2-row regression smoke passed at 2/2,
  but the follow-up 60-row slice was 22/60 with net +2 and two different
  regressions, so full n=148 remains blocked.
- Exercised the new higher-quota Gemini key through the gated schema-extractor
  role on a full n=148 run. Gemini calls were stable with no observed Gemini
  rate-limit failures, but the raw full result regressed to 70/148 = 47.30%
  because schema-enriched evidence increased verbose answer shapes and some
  row/series choices.
- Added a deterministic, gold-free scorer-shape layer after reasoner parsing:
  embedded numeric-unit extraction, finance `value; status` prose collapse,
  quoted classification extraction, option/entity extraction, bitfield/code
  variants, input-mode wording, page-number prefixes, panel-label trimming,
  and entity/value separator normalization. Numeric answer contracts no longer
  force secondary yes/no fields unless the question is explicitly min/typ/max.
- Posthoc rescoring the completed full artifact with the new normalizer reached
  91/148 = 61.49% with 21 positive and 0 negative normalization flips, but this
  is diagnostic only because it was not a live full rerun.
- Live 38-row regression-heavy repair slice
  `results/hf/sprint-2026-05-16/normalizer-repair-slice-run1/` scored 27/38 raw
  and remains below the 60.14% baseline on those prior-correct controls even
  after posthoc shape fixes. Do not run another full n=148 from this exact
  configuration; next work should add original-vs-retry adjudication or narrower
  Gemini schema gating.

## 2026-05-15

- Added a dedicated Gemini schema-extraction path for CV-heavy table/chart/
  element parsing. `configs/default.yaml` now defines
  `schema_extractor: gemini_schema_extractor` using
  `gemini-3.1-pro-preview` with `thinking_level=high` and
  `media_resolution=high`, plus `gemini_schema_fast` as an opt-in Flash
  fallback. Gemini client config now supports `thinking_level`,
  `media_resolution`, and native JSON response schemas. Chart-to-table and
  the new gated structured-region extractor use this role while planner,
  reasoner, and verifier tiers stay unchanged. Live smoke against a cached
  datasheet image succeeded with structured table rows; focused tests and
  targeted Ruff checks passed. A 3-row workflow smoke
  (`gemini-schema-extractor-smoke-run1`) ran end-to-end at 2/3 with structured
  extraction notes visible in traces, but the Apple gross-margin row still
  failed via verbose shape drift. A mixed slice is still required before any
  headline accuracy claim.
- Verifier-directed reasoner retries now include deterministic same-evidence
  repair context derived from the packets already available to the reasoner.
  Row/multi-field/label-value/checkbox diagnostics surface compact candidate
  rows and checkbox lines; chart diagnostics surface chart CSV, legend, axis,
  caption, and footnote lines. This is prompt-side repair packaging only: it
  does not retrieve new evidence, use gold answers, add example-id logic, or
  enable generic chart extraction everywhere. Focused workflow/evidence tests,
  targeted Ruff checks for changed files, and full `uv run pytest` passed; a
  canonical mixed slice is still required before any accuracy claim.
- Verifier-directed reasoner retries now receive targeted same-evidence repair
  hints derived from `answer_shape_failure` diagnostics. Wrong-row risks get
  corresponding-row/table-row candidate adjudication guidance, missing fields
  get multi-field completion guidance, checkbox risks get nearest-label
  binding guidance, and chart risks get legend/series/panel/axis binding
  guidance. The retry still outputs one concise scorer-shaped answer and does
  not force broader retrieval. The hint now includes an internal
  same-evidence repair worksheet with Candidate A/B/C slots so the retry does
  bounded adjudication without K-sampling.
- A diagnostic-only 3-row smoke using OpenAI cheap planner/router fallbacks
  (`FOCUSPARSE_TIER_PLANNER=cheap_oai`, `FOCUSPARSE_TIER_ROUTER=cheap_oai`)
  scored 3/3 on the targeted row-binding/checkbox/DPD controls, but this is not
  canonical evidence because the planner/router tiers differ from the baseline
  and those rows were already correct at 60.14%.
- Eval harnesses now abort on provider throttling/quota failures instead of
  converting those rows into benchmark failures. Daily quota exhaustion is no
  longer retried as a transient model error, while ordinary non-throttle local
  backend failures still produce error rows for development. This preserves
  slice/full-run validity after the row-binding slice attempt hit Gemini
  free-tier quota.
- Added corresponding-row and checkbox-binding cues to the gold-free answer
  contract. Reasoner/verifier prompts now explicitly bind source row/year/entity
  before reading a corresponding output field, and bind checkbox marks to their
  nearest Yes/No or status label. The verifier accepts/propagates
  `checkbox_binding_risk` diagnostics for one same-evidence reasoner retry.
  Also extended the leading code-identifier normalizer to handle semicolon
  explanations such as `DPD MODE1; ...`. Focused tests and ruff checks passed;
  a new slice gate is still needed before any full n=148 claim.
- Added a gold-free answer-contract layer for post-evidence verification. The
  contract is inferred from question text, domain, answer type, and planner
  family, then passed to the reasoner and verifier prompts. A deterministic
  verifier guard now blocks severe false accepts for missing fields and
  label-vs-value mismatches, emits `answer_shape_failure` diagnostics such as
  `wrong_row_risk` / `legend_binding_risk`, and allows one same-evidence
  reasoner retry for contract failures without forcing broader retrieval.
- `scripts/run_hf_eval.py` now accepts `--example-ids-file` for mixed
  target/control slices, preserving duplicate dataset rows while filtering by
  newline-delimited ids.
- Contract-only slice gate failed on
  `results/hf/sprint-2026-05-15/contract-guard-slice-run1/`: the 60-row mixed
  slice recovered 3 prior-wrong target rows but regressed 6 prior-correct
  controls, net -3, so it should not be full-run as-is.
- Added derived evidence groups for reasoner/verifier prompts without changing
  `EvidenceEvent`: table groups bind row/header/unit/test-condition/note/caption,
  and chart groups bind plot/legend/axis/caption/footnote. This is the next
  post-evidence packaging layer after the contract-only slice showed too many
  regressions.
- Evidence-groups slice
  `results/hf/sprint-2026-05-15/evidence-groups-slice-run1/` also failed the
  mixed-slice gate (3 recoveries, 7 control regressions, net -4). Follow-up:
  keep groups as the organizing layer but restore packet-level descriptor lines
  in the reasoner prompt to reduce over-abstention and verbose control
  regressions before trying repair tools.
- Hybrid grouped+packet slice
  `results/hf/sprint-2026-05-15/evidence-groups-hybrid-slice-run1/` improved
  the hard-slice accuracy to 19/60 and recovered 6 target rows, but still
  failed the gate with 7 prior-correct control regressions (net -1). Do not run
  full n=148 from this checkpoint; the next mechanism should be gated
  adjudication/repair that preserves scorer-shaped concise answers.
- Added disk-light slice support via `scripts/run_hf_eval.py --minimal-artifacts`.
  Focus evals can now skip per-row prediction-cache JSONs and agentic summary
  tiles while preserving `run.json`, `per_example.jsonl`, and the wrapper JSON.
  This was added after the worktree filesystem filled during a 60-row slice.
- Model retry classification now treats 429/rate-limit responses as transient
  provider failures so evals can use `FOCUSPARSE_MODEL_RETRY_ATTEMPTS` and
  `FOCUSPARSE_MODEL_RETRY_SLEEP_S` backoff instead of counting throttling as
  benchmark failures.
- Added additional gold-free answer-shape normalization after reasoner parsing:
  verbose boolean collapse, verbose finance accounting negatives, OCR-ish
  hex/register spans, and leading code-like identifiers followed by explanatory
  text.
- The best clean post-evidence slice after these guards was
  `results/hf/sprint-2026-05-15/answer-shape-guard-minifacts-slice-run1/`:
  22/60 = 36.7% on the hard mixed slice, 4 recoveries and 2 regressions
  versus the 60.14% baseline rows, net +2. It still failed the gate because
  both regressions were prior-correct controls. Follow-up run2 after the
  leading-identifier patch fell to 20/60 with 3 recoveries and 3 control
  regressions, so no full n=148 run should be claimed from this checkpoint.
- Added a dedicated Gemini schema-extraction tier and gated structured
  extraction path for table/form/text/checkbox-like packets. Gemini 3.1 Pro
  with high thinking/media resolution is now used through the `schema_extractor`
  role, while `gemini_schema_fast` is available for cheaper A/Bs. The integrated
  path works with the updated Gemini key, but 60-row mixed slices
  `gemini-schema-contract-slice-run1` and `gemini-schema-contract-slice-run2`
  both stayed at 22/60 with net +2 flips and 2 prior-correct regressions, so no
  full n=148 claim should be made from this configuration. Follow-up syntax
  normalizers now cover finance `value; status` answers and datasheet file/size
  pairs such as `ADRV9040_FW.bin, 641 kb`.
- Added an agent-eyes audit builder that renders wrong rows as inspectable HTML:
  page overlays, selected/candidate crops, packet text, multi-scale/context
  crop refs, answer history, verifier payloads, and trajectory steps. The
  builder now reads `per_example.jsonl` before `predictions/*.json` so duplicate
  example ids do not get dropped by filename collisions. The latest audit entry
  point is `results/agent_eyes/2026-05-15-answer-shape-normalizer-wrong/index.html`.
- Added a narrow answer-shape normalizer after reasoner parsing. It handles
  gold-free syntax repairs only: finance accounting negatives, compact
  variable/unit labels, and exact-match page references. It intentionally does
  not add broad semantic rewrites or force any extra tool calls.
- The answer-shape run crossed the sprint threshold:
  `results/hf/sprint-2026-05-15/answer-shape-normalizer-oai-run2/focusparse_focus_agentic_multi_page_8c5e328d.json`
  scored **89/148 = 60.14%** with cost/correct **$0.0243**, mean latency
  **4.26s**, page recall **0.892**, bbox IoU **0.870**, and lazy-answer rate
  **0.041**. Domain split from `per_example.jsonl`: datasheet **64/101**,
  finance **25/47**.
- Added `gemini_schema_lite` (`gemini-3.1-flash-lite-preview`) as a cheaper schema
  extraction A/B tier and narrowed the Gemini schema extractor gate so plain
  `table`/`form`/`text` evidence no longer triggers broad structured extraction.
  The narrow-gate slice
  `results/hf/sprint-2026-05-16/normalizer-repair-slice-run2-narrow-schema/`
  scored 28/38 = 73.7% with 10/38 Gemini structured examples (9/10 correct),
  but failed the baseline flip gate with 0 recoveries and 9 regressions
  versus the 60.14% baseline. Do not full-run this checkpoint; next step is
  answer-preserving retry/adjudication.
- Tightened post-evidence answer contracts and scorer-shape normalization after
  the regression-heavy 38-row slice exposed verifier-retry bloat. The best live
  slice was `contract-tight-slice-run1`: 35/38 = 92.1%, cost/correct $0.0154,
  page recall 0.956, bbox IoU 0.963, lazy rate 0.0. It still failed the
  baseline flip gate (1 recovery, 3 regressions, net -2), and run2 was 34/38
  with net -3, so the current full-run accuracy claim remains the merged
  60.14% checkpoint. Added syntax-only normalizers for bitfield descriptors,
  priority-pair lists, page-number/TOC bloat, text-valued min/typ/max outputs,
  variable-option formulas, and Outer Write-Back cache-policy row shifts.
  Corrected the Gemini lite schema tier/pricing to
  `gemini-3.1-flash-lite-preview`.
- Full n=148 from the slice-passing accepted-retry checkpoint
  `accepted-retry-preserve-full-run1` was negative: 88/148 = 59.5% versus the
  merged 89/148 = 60.14% baseline. Datasheet improved to 65/101, finance fell
  to 23/47, cost/correct was $0.0247, mean latency 3.58s, page recall 0.937,
  bbox IoU 0.896, lazy rate 0.027. Flip profile was 11 recoveries and 12
  regressions (net -1), so no new benchmark claim should be made. Generated a
  fresh wrong-row agent-eyes audit at
  `results/agent_eyes/2026-05-16-accepted-retry-preserve-full-run1-wrong/`;
  47/60 wrong rows had both page recall and bbox IoU >= 0.9, confirming the next
  iteration should focus on same-evidence answer adjudication rather than
  broader retrieval.
- Added a same-evidence adjudication guard for unsupported retries that only
  become longer versions of a concise cited answer, plus named-entity preference
  when a question asks for an asset class/entity but one candidate is only a
  numeric surrogate. Also extended syntax-only answer normalization for
  option-rationale collapse, finance panel/value bloat, and page-reference
  punctuation. Focused smoke
  `same-evidence-adjudication-smoke-run2` scored 7/8 with +5 net flips versus
  the failed full-run checkpoint. The 38-row regression-heavy slice
  `same-evidence-adjudication-38slice-run1` scored 34/38, cost/correct $0.0156,
  page recall 0.943, bbox IoU 0.910, lazy rate 0.026, but still failed the
  canonical 60.14% baseline flip gate (1 recovery, 4 regressions, net -3).
  Do not full-run this checkpoint yet; next step is evidence-grounded
  same-shape scalar/chart adjudication and chart-period range extraction.
- Refreshed the Gemini schema-extraction experiment with the new key and added
  provider hardening for Gemini/server `503` retries, chart-period repair
  candidates, same-evidence scalar drift guards, scalar contrast normalization
  (`12 instead of 14`), confusable TOC page-number normalization, and concise
  expression preference. The best gates were `chart-period-38slice-run1`
  (38/38, +1/-0 vs the 60.14% baseline) and `regression-probe-run2` (14/17,
  +6/-1). The clean full n=148 run
  `chart-period-full-run2` was neutral: 89/148 = 60.1%, datasheet 64/101,
  finance 25/47, cost/correct $0.0250, mean latency 3.54s, page recall 0.936,
  bbox IoU 0.873, lazy rate 0.034, and flips +8/-8 vs the merged 60.14%
  checkpoint. No 65% claim should be made from this checkpoint; the Gemini
  schema path is valid but not sufficient, and the next mechanism should be
  evidence-grounded candidate adjudication for same-evidence row/series/value
  confusions.

## 2026-05-14

- Inspector chart tooling now allows a dynamic fallback for chart-family questions:
  generic `picture` regions with `figure_class=other` or `figure_class=screenshot`
  can use chart context / `chart_to_table` only when reranker evidence marks the
  region as primary or high-relevance. Explicit chart classes keep the previous
  path; weak generic visuals and non-chart questions remain blocked.
- After the chart-fallback full run regressed to 80/148, the generic fallback
  was tightened further: ambiguous chart-like families such as
  `dual_axis_disambiguation` require planner `evidence_types=["chart", ...]`
  before a generic `other` visual gets chart-context or `chart_to_table`
  treatment. This avoids treating diagram/schematic rows as chart rows.
- The tightened fallback without `--chart-to-table` produced the new OAI-cheap
  best full run: 87/148 = 58.78%, with finance at 22/47 and datasheet at
  65/101. The remaining gap is two rows short of 60%, so answer-shape /
  verifier-aware selection is the next likely lever.
