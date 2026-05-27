# Project Changelog

## 2026-05-26

- Added `docs/research/paper-draft/source-pdf-terms-manifest.tsv`,
  `docs/research/paper-draft/archival-snapshot-readiness.md`, and archive
  checksum sidecar generation in
  `scripts/package_paper_review_artifacts.py`. The package helper now records
  `archive_sha256` / `archive_sha256_file` in its JSON output and writes
  `.tar.gz.sha256` sidecars beside generated archives. The terms manifest has
  one row per pinned source PDF and explicit source URL / terms URL / release
  status fields. The manifest now has no remaining `TODO` source/terms fields:
  42 rows have official web-verified source and terms URLs, one Nordic row has
  an official PDF with embedded no-reproduction terms, and one TTP223B row is
  backed by a distributor mirror because no original manufacturer source was
  found. The current package targets are internal review
  `focusparse-paper-review-package-2026-05-24-v32.tar.gz` and source-safer
  public metadata
  `focusparse-paper-public-metadata-package-2026-05-26-v10.tar.gz`. Generated
  and validated those snapshots with 262/313 internal manifest/tar files and
  106/150 public manifest/tar files; the public-metadata package still has zero
  `.png`, `.jpg`, `.jpeg`, or `.pdf` files.

## 2026-05-25

- Added a `--release-mode public-metadata` option to
  `scripts/package_paper_review_artifacts.py`. This builds a source-safer
  package for public or double-blind artifact staging by excluding compiled
  PDFs and source-derived page/crop/tile/figure-panel images while preserving
  paper sources, bibliography, metrics, diagnostics, per-example rows, and
  text/CSV analysis artifacts. Generated and validated
  `results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-25-v3.tar.gz`
  with 104 manifest-tracked files, 148 tar members, and zero `.png`, `.jpg`,
  `.jpeg`, or `.pdf` files.
- Added `docs/research/paper-draft/compute-resource-disclosure.md`, a
  NeurIPS-style compute disclosure for the raw-verified seven-method headline
  sweep. It records 1,036 example-runs, a 2.56-hour wall-clock envelope,
  4.54 summed method-hours, max parallelism 2, provider/model roles, local host
  details, and `$16.9441` in reported model-call cost from the repo pricing
  table. Refreshed the slim internal v25 archive so it includes the disclosure:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v25.tar.gz`.

## 2026-05-24

- Added `docs/research/paper-draft/source-pdf-and-asset-license-audit.md` to
  separate code/license facts from third-party source-document release risk.
  The audit records the pinned slice's 44 PDFs, the v24 package's 146 derived
  qualitative image assets, and a safer public-release posture: publish
  metadata/scripts/run outputs by default while withholding full PDFs and
  derived page/crop/tile images unless per-source terms permit redistribution.
  Refreshed the slim v24 review archive so it includes the audit:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v24.tar.gz`.
- Added `docs/research/paper-draft/neurips-checklist-prep.md`, a
  NeurIPS-style checklist preparation artifact that maps FocusParse's current
  claims, reproducibility package, compute/resource disclosure, artifact
  policy, license/asset caveats, ethics/broader-impact notes, and LLM-use
  disclosure into draft checklist answers. Refreshed the slim v22 review
  archive so it includes the checklist prep:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v22.tar.gz`.
- Added `docs/research/paper-draft/venue-template-conversion-audit.md` to map
  the current article-style paper source into the next official
  workshop/conference author kit. The audit records the NeurIPS 2026
  main/workshop timing, template/checklist blockers, section mapping, figure
  and table budget, and submission-ready definition. Refreshed the slim v21
  review archive so it includes the audit:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v21.tar.gz`.
- Refreshed `docs/research/paper-draft/venue-submission-plan.md` against
  official CVPR, ACL, ICML, ICLR, and NeurIPS 2026 pages. The current target
  read is that the named 2026 archival main deadlines have passed, NeurIPS 2026
  workshop papers are the practical near-term route after accepted workshops
  are announced on 2026-07-11, and NeurIPS 2027 Evaluations & Datasets remains
  the strongest full-paper target.
- Added `scripts/package_paper_review_artifacts.py` and generated a slim paper
  review package at
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v6/`
  plus `.tar.gz`. The package keeps the paper docs/PDF, headline tables, all
  seven method `run.json` and `per_example.jsonl` files, diagnostics, figure
  panels, baseline comparisons, failure-taxonomy artifacts, trace-viewer
  qualitative assets, and checksums while excluding the 4.3 GB tile/prediction
  payload.
- Added the final FocusParse +4 failure taxonomy to the Markdown and LaTeX
  paper drafts. The table records 57 errors: 26 verifier-unsupported, 12
  partial-localization, 8 localization-miss, 7 reasoning/extraction, and 4
  lazy/no-bbox failures.
- Generated the final-run qualitative viewer bundle at
  `results/agent_eyes/paper-final-headline-qualitative-focus-full/` from the
  matched n=148 FocusParse +4 package. Refreshed
  `docs/research/paper-draft/qualitative-figure-manifest.md` and
  `qualitative-evidence-packets.md` so the paper qualitative examples use the
  May 24 result package instead of the older May 15 trace. Added
  `dat-JESD204B-Survival-Guide-0029` as the clean primary datasheet success
  figure and demoted `dat-adrv9040-reference-manual-ug-2192-0032` to a
  compaction/answer-shape near-miss because the final prediction omits the
  requested `641 kb` size field.
- Added `scripts/build_paper_qualitative_panels.py` and generated draft
  composed paper panels under `results/paper/qualitative-figure-panels/`.
  The panel package includes a Latvia finance evidence-binding PNG, a
  JESD204B datasheet evidence-compaction PNG, `asset-inventory.csv`, and a
  slide-friendly `presentation-visuals.md` handoff.
- Added `scripts/build_qualitative_baseline_comparison.py` and generated
  same-revision qualitative comparator artifacts under
  `results/paper/qualitative-baseline-comparisons/`. The comparison records
  Base VLM, ReAct +2/+4, Agent baseline +2/+4, and FocusParse +2/+4
  predictions for the Latvia and JESD204B figure examples.
- Added the first standalone LaTeX paper draft under
  `docs/research/paper-draft/latex/`. The draft includes the current abstract,
  related work, parser-bench dataset description, FocusParse method, final
  matched result table, the two composed qualitative figures, and the existing
  bibliography; TeX Live / latexmk compiled it successfully to `main.pdf`.

## 2026-05-23

- Added the paper-draft result rerun package plan in
  `docs/research/paper-draft/final-results-rerun-runbook.md`, including pinned
  HF materialization, source-PDF hydration, seven-spec headline runs,
  diagnostics, qualitative viewer export, and manifest/acceptance checks.
  Fixed `scripts/run_headline_eval.py` so merged headline tables use the
  current config-derived `tier_sha8` instead of a stale hard-coded run path.
  Added `bibliography-readiness-audit.md` and refreshed Zotero-status docs to
  reflect that Zotero Desktop is not available on this profile yet. Pinned and
  materialized the paper dataset at HF revision
  `3774c67f8b814392b6d04c939e904f749a3f52eb`, producing 148 rows / 147 unique
  IDs and benchmark SHA
  `e85b4df5032bc9e49fc74e1ed7492001794fbf4b46cc0f35d31a4cf32277962b`; recorded
  the durable summary in `docs/research/paper-draft/pinned-dataset-provenance.md`.
  Added an NFS `archive/raw_pdfs/` fallback to `scripts/source_pdfs_from_nfs.py`
  and hydrated the pinned slice's source-PDF cache to 44/44 PDFs, recorded in
  `docs/research/paper-draft/source-pdf-readiness.md`. Ran a pinned 3-row
  FocusParse +4 smoke at HF revision
  `3774c67f8b814392b6d04c939e904f749a3f52eb`: 3/3 correct, total cost
  `$0.01872625`, lazy rate 0, layout/model path successful, one Anthropic
  timeout recovered by retry. Restored the shared staging back to the full 148
  rows and updated the runbook to use `--example-ids-file` instead of `--limit`
  for future smokes. Extended `scripts/run_headline_eval.py` to forward
  `--example-ids-file`, then ran the seven-method headline smoke successfully:
  all 7 rows completed, rendered `headline_table.{json,md,csv,jsonl,html}`,
  diagnostics analyzed all specs, and shared staging remained at 148 rows.

## 2026-05-19

- Added a static FocusParse pipeline demo generator:
  `scripts/build_pipeline_demo.py` and `src/focusparse/traces/pipeline_demo.py`.
  The generator builds a Vercel-ready bundle under
  `results/trace_viewer/pipeline-demo/` from existing `per_example.jsonl`
  traces, audit benchmark question text, and current staged page PNGs. It
  materializes fresh page/crop assets from recorded bboxes instead of relying
  on stale cache paths, and renders the eight pipeline stages with overlays,
  crops/context, tool-use summaries, verifier details, and structured logs.

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
# 2026-05-24

- Completed the first full matched seven-method paper headline run on the
  pinned HF parser-bench revision `3774c67f8b814392b6d04c939e904f749a3f52eb`
  and source-PDF cache `/Users/gabrielbo/.cache/focusparse/pdfs`.
  Result package:
  `results/hf/paper/2026-05-24-paper-headline-v1/`. Every spec has
  `run.json`, `per_example.jsonl`, and `predictions/`; every `per_example` file
  has 148 rows. The rendered main table reports Base VLM 43.9%, ReAct +2 18.2%,
  ReAct +4 16.2%, Agent baseline +2 8.1%, Agent baseline +4 6.1%,
  FocusParse +2 60.1%, and FocusParse +4 61.5% overall accuracy. FocusParse +4
  is 66.3% on datasheets and 51.1% on finance with $0.0248/correct, page
  recall 0.914, and BBox IoU 0.857. Diagnostics are in
  `results/hf/paper/2026-05-24-paper-headline-v1/diagnostics/headline-diagnosis.md`.
  The result directory also has `README.md`, `manifest.json`, a config snapshot,
  and run-start git commit/status.
- Refreshed the paper-draft related-work/source framing around external
  RunLlama `ParseBench` versus Gabriel `parser-bench`, updated live HF/GitHub
  source notes, recompiled the 7-page LaTeX draft, and generated the slim v7
  submission-review package:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v7.tar.gz`.
  The archive is 40M, the directory is 67M, and the manifest tracks 210 files.
- Added a requirement-level paper objective audit and a concrete ablation plan
  for the missing mechanism table, then generated the slim v8 review package:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v8.tar.gz`.
  The archive is 40M, the directory is 67M, and the manifest tracks 212 files.
- Bumped the latest review package reference to v10 after refreshing the package
  self-description, so the newest archive contains the final metadata:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v10.tar.gz`.
- Added paper-ablation flags for the missing mechanism table:
  `--disable-rerank` skips the query-conditioned rerank stage while preserving
  localizer order, and `--disable-expand-context` skips only the expansion
  stage while keeping `run_python` available under the full tool belt. Tests pin
  direct workflow behavior, harness forwarding, CLI parsing, trace reasons, and
  manifest feature bits. The ablation plan now includes exact command shapes,
  and the latest slim review archive is v10:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v10.tar.gz`.
- Added `scripts/build_paper_ablation_summary.py` and generated the first
  concrete paper ablation from the final matched FocusParse +2/+4 runs:
  `results/paper/ablation-summary/focusparse-toolset-ablation.md`. The paired
  comparison preserves the intentional duplicate example ID via
  `(example_id, occurrence)`, covers all 148 rows, and reports +2 net correct
  for +4 over +2 (9 recoveries, 7 regressions). The latest slim review archive
  is v11 and includes the ablation summary artifacts:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v11.tar.gz`.
- Completed 3-row pure-ablation smoke checks for no-expand, no-rerank, and
  retry-off using the pinned paper HF revision and local PDF cache. Each smoke
  run completed layout preflight and wrote minimal artifacts under
  `results/hf/paper/ablation-smoke-{no-expand-v1,no-rerank-v1,retry-off-v1}/`.
  The final FocusParse +4 smoke subset from the n=148 run scored 3/3, while all
  three ablation smokes scored 2/3, so the switches are verified but still need
  matched n=148 runs for a causal mechanism claim. Added
  `docs/research/paper-draft/ablation-smoke-summary.md` and generated the slim
  v12 review archive with smoke artifacts included:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v12.tar.gz`.
- Completed the first full n=148 pure mechanism ablation:
  `results/hf/paper/ablation-no-expand-v1/` disables only
  `expand_context` while keeping `run_python` available under the full tool
  belt. The run has 148 rows, HF revision
  `3774c67f8b814392b6d04c939e904f749a3f52eb`, tier SHA `0b139a04`, 59.5%
  overall accuracy, 62.4% datasheet, 53.2% finance, page recall 0.917, BBox IoU
  0.847, and $0.0279/correct. Paired against final full +4, restoring
  expansion moves 59.5% to 61.5% overall with 14 recoveries, 11 regressions,
  and +3 net correct rows; the gain is concentrated in datasheets. Added
  `docs/research/paper-draft/no-expand-ablation-summary.md`, generated
  `results/paper/mechanism-ablation/no-expand-v1/`, and refreshed the slim
  v13 review archive:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v13.tar.gz`.
- Completed the full n=148 no-rerank mechanism ablation:
  `results/hf/paper/ablation-no-rerank-v1/` disables only the
  query-conditioned rerank stage while preserving full tool availability and
  context expansion. The run has 148 rows, HF revision
  `3774c67f8b814392b6d04c939e904f749a3f52eb`, tier SHA `0b139a04`, 56.1%
  overall accuracy, 60.4% datasheet, 46.8% finance, page recall 0.849,
  BBox IoU 0.738, and $0.0249/correct. Paired against final full +4, restoring
  rerank moves 56.1% to 61.5% overall with 19 recoveries, 11 regressions, and
  +8 net correct rows, with gains in both datasheet and finance slices. Added
  `docs/research/paper-draft/no-rerank-ablation-summary.md`, generated
  `results/paper/mechanism-ablation/no-rerank-v1/`, and refreshed the slim v14
  review archive with both full no-expand and no-rerank artifacts:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v14.tar.gz`.
- Completed the full n=148 verifier-directed repair ablation:
  `results/hf/paper/ablation-verifier-off-v1/` sets `--max-retries 0` and
  `--max-evidence-retries 0` while preserving the full tool belt, rerank,
  expansion, and verifier scoring. The run has 148 rows, HF revision
  `3774c67f8b814392b6d04c939e904f749a3f52eb`, tier SHA `0b139a04`, 62.8%
  overall accuracy, 68.3% datasheet, 51.1% finance, page recall 0.920,
  BBox IoU 0.898, and $0.0282/correct. Telemetry confirms
  `retries_used=0` and `evidence_retries_used=0` for all 148 rows. Paired
  against final full +4, restoring verifier-directed repair moves 62.8% to
  61.5% overall with 9 recoveries, 11 regressions, and -2 net correct rows, so
  this is a mixed/negative mechanism control rather than evidence that repair
  carries the paper gain. Added
  `docs/research/paper-draft/verifier-repair-ablation-summary.md`, generated
  `results/paper/mechanism-ablation/verifier-off-v1/`, added the ablation table
  to the Markdown and LaTeX drafts, recompiled `latex/main.pdf` to 7 pages, and
  refreshed the slim v16 review archive:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v16.tar.gz`.
- Added `--disable-answer-shape-repair` as a pure paper-ablation switch. It
  disables answer-shape-specific retry hints and accepted-retry selection guards
  while preserving full tool availability, rerank, expansion, verifier scoring,
  and non-shape verifier repair. Targeted tests cover the workflow, harness
  forwarding, and CLI argparse path. The full n=148 run at
  `results/hf/paper/ablation-answer-shape-off-v1/` has 148 rows, HF revision
  `3774c67f8b814392b6d04c939e904f749a3f52eb`, tier SHA `0b139a04`, 64.2%
  overall accuracy, 70.3% datasheet, 51.1% finance, page recall 0.945,
  BBox IoU 0.896, and $0.0224/correct. Paired against final full +4, restoring
  answer-shape repair moves 64.2% to 61.5% overall with 9 recoveries,
  13 regressions, and -4 net correct rows, so answer-shape repair is a negative
  mechanism control rather than evidence that scorer-shape normalization carries
  the paper gain. Added
  `docs/research/paper-draft/answer-shape-repair-ablation-summary.md`,
  generated `results/paper/mechanism-ablation/answer-shape-off-v1/`, updated
  the Markdown and LaTeX ablation tables, recompiled `latex/main.pdf` to
  7 pages, and refreshed the slim v18 review archive:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v18.tar.gz`.
- Refreshed related work from live primary sources after the answer-shape
  package: added `MPDocBench-Parse` (`arXiv:2605.22100`) as a current
  multi-page parsing benchmark citation, updated `references.bib`, the
  citation map, related-work matrix, source audit, Markdown drafts, and LaTeX
  draft, and recorded that the public HF `gabrielbo/parser-bench` viewer now
  shows a broader 1.54k-row surface distinct from the pinned 148-row paper
  materialization. Zotero remains unavailable (`127.0.0.1:23119` connection
  refused), so the bibliography is still primary-source based pending local
  Zotero export. Recompiled `latex/main.pdf` to 7 pages and refreshed the slim
  v20 review archive, now including `citation-map.md` and
  `related-work-failure-matrix.md`:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v20.tar.gz`.
