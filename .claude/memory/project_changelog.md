# Project Changelog

## 2026-05-16

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
