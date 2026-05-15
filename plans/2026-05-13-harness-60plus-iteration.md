# Harness 60%+ Iteration — Combined Plan (Harness Improvements + Benchmark Audit)

## Overview

Drive `focus_agentic_multi_page` accuracy on parser-bench n=148 from the
current **49.3% main-stack baseline** to **≥60.0%** (preferably higher).
Attack surface, in dependency order:

1. **Reproduce baseline** on `harness-60plus-iteration` (must land in
   [47.0, 51.5] before iterating — otherwise we're chasing config drift).
2. **Failure-mode triage**: bucket every wrong example into one of
   `bad_layout`, `wrong_page`, `wrong_extraction`,
   `verifier_rejected_correct`, `tool_missed`, `lazy_abstain`.
3. **Benchmark audit on the failure set**: each row is
   `harness_error`, `unanswerable`, `golden_incorrect`, or `ambiguous`.
   `golden_incorrect`/`unanswerable` rows produce upstream parser-bench
   fix proposals; only `harness_error`/`ambiguous` rows count against us.
4. **Iterate the harness** against bucket sizes, biggest bucket first:
   per-domain reasoner format-hint routing → reasoner self-consistency
   on `wrong_extraction` → tool-selection gates in inspect/expand →
   verifier abstain-routing → bbox/crop refinement.
5. **Gate at 60%+** on a clean n=148 run with
   `lazy_answer_rate ≤ baseline + 1pp` and `bbox_iou` not regressing
   more than 2pp.

This plan subordinates itself to the active framing plan
[`plans/2026-04-29-research-driven-eval-framework.md`](2026-04-29-research-driven-eval-framework.md).
Each phase below must answer:

- Which **cell** in the headline 4-method × 2-task × 2-metric table does
  it move? (Always `Our harness +4 / {Datasheets, Finance} / accuracy`
  for this plan unless noted.)
- By how much (predicted pp delta)?
- Through what **stage-level mechanism** (use one of `bbox_iou`,
  `page_recall`, `cited_evidence_completeness`, `verifier_abstain_rate`,
  `lazy_answer_rate`, `tool_calls_mean`)?

## Current State Analysis

### Baseline numbers (canonical run)

`results/hf/sprint-2026-05-13/main-stack-run1/focusparse_focus_agentic_multi_page_333fe987.json`
(n=148, `agentic_multi_page`, all Phase 5/6a/7 merged):

| Metric               | Value                     |
| -------------------- | ------------------------- |
| Overall accuracy     | **49.3%** (73/148)        |
| Datasheet accuracy   | 56.7% (n=101)             |
| Finance accuracy     | 40.9% (n=47)              |
| Page recall          | 0.866                     |
| Bbox IoU             | 0.799                     |
| Lazy answer rate     | 0.081                     |
| Tool calls / example | 0.95 (skew toward 1 tool) |
| Cost per correct     | $0.026                    |
| Total cost (n=148)   | $1.89                     |

### Failure prior (from 2026-05-11 afternoon MEMORY entry)

- **81% of wrong examples are post-localization** (IoU≥0.3,
  page_recall≥0.5). The localizer is not the bottleneck.
- Within that 81%: ~16 examples are prompt-fixable (gold-in-pred,
  pred-in-gold, normalized-match); ~43 are genuine reasoner errors
  needing self-consistency or a stronger model.
- Phase 6a's `exact_match` prompt tightening was **domain-divergent**:
  datasheets +7.3pp, finance −11.4pp. The global prompt is over-tuned
  for datasheets and hurts finance.

### What we already have on this branch

- Clean checkout off `origin/main` at `700af5f`.
- All Phase 5 (`_should_use_react_inspector` AND-gating), Phase 6a
  (`exact_match` 4-rule prompt), Phase 7 (`chart_to_table_llm`) merges.
- Layout endpoint on Modal
  (`https://llamaindex--layout-v3-triton-layoutv3triton-serve.modal.run`)
  with `LAYOUT_EXTRACTION_V3_MODAL_TOKEN`.
- LLM response cache wiring
  (`src/focusparse/cache/store.py::LLMResponseCache`,
  `src/focusparse/models/tiers.py::CachingModelClient`). Reasoner +
  verifier intentionally bypass cache; only planner + localizer_rerank
  replay. Use `--llm-cache-dir cache/llm_responses/<run-name>
--llm-cache-mode record-or-replay` for cheap A/B replication on
  smaller slices.
- Domain is already piped to `QuestionEvent.domain` in
  `src/focusparse/pipeline/events.py:21`
  (`"finance" | "datasheet" | None`) from `workflow.py:409`.
- `aggregate_by_domain` (`src/focusparse/eval/metrics.py`) buckets every
  run by `domain` for free per-domain accuracy / CI numbers.

### What we don't yet have

- A failure-bucket spreadsheet for the baseline n=148.
- A per-failure golden-audit verdict file.
- Per-domain branching of `_format_hint` (the highest-EV cheap lever).
- Reasoner self-consistency (K≥2 sampling with conciseness/confidence
  picker) for the `wrong_extraction` bucket.
- Tool-selection gates that fire `chart_to_table` / `expand_context` on
  the examples where they would help but currently don't run.
- A verifier abstain-routing pass that escalates to a fresh reasoner
  attempt when the verifier rejects a non-Unanswerable answer but the
  reasoner could still produce a supported answer with neighbor context.

## Desired End State

A clean run

```bash
uv run python scripts/run_hf_eval.py --agent focus \
  --protocol agentic_multi_page --hf-split validation \
  --output-dir results/hf/sprint-2026-05-13/60plus-final-run1/
```

reports:

| Metric             | Target                            |
| ------------------ | --------------------------------- |
| Overall accuracy   | **≥ 60.0%** (88/148 or better)    |
| Datasheet accuracy | ≥ 60.0% (with finance recovered)  |
| Finance accuracy   | ≥ 50.0% (recovered from 40.9%)    |
| Page recall        | ≥ 0.85 (not regressing)           |
| Bbox IoU           | ≥ 0.78 (no more than 2pp drop)    |
| Lazy answer rate   | ≤ 0.091 (baseline + 1pp)          |
| Cost per correct   | ≤ $0.04 (within 1.5× of baseline) |

Plus:

- `thoughts/shared/audits/2026-05-13-failure-triage.md` — per-example
  bucket assignment with verdict and one-line rationale.
- `thoughts/shared/audits/2026-05-13-golden-audit.md` — per-example
  audit verdict for the failure set, including upstream parser-bench
  fix candidates.
- `docs/research/2026-05-13-harness-60plus-results.md` — final writeup
  with per-phase A/B deltas and CIs.
- `.claude/memory/project_changelog.md` — one-line entries per
  substantive commit.

## What We're NOT Doing

- **Not changing the comparator methods** (Base VLM, ReAct, Agent
  baseline). Their numbers stand; only `Our harness +4 tools / Datasheets
/ accuracy` and `Our harness +4 tools / Finance / accuracy` move.
- **Not adding a 4th `inspect_region` mode.** `CLAUDE.md` flags this as
  a load-bearing contract (3 modes: image / element / region). A 4th
  mode requires a plan update first.
- **Not modifying the parser-bench submodule.** Golden-incorrect
  findings go into an upstream-PR proposal file; we keep our local
  scorer aligned to the published parser-bench scorer ±2pp on the
  reproducibility gate row.
- **Not changing tier config** as part of accuracy iteration. If a
  change needs a different tier, save it as a sibling
  `configs/<experiment>.yaml` and pass via `--config-override`.
  `tier_sha8 = 333fe987` is the namespace for this sprint.
- **Not pursuing a single 10pp jump.** The math says we need ~3 cheap
  +3pp wins layered without regression. Single-experiment cliffs are
  red flags for overfitting.
- **Not running tiny smokes as the headline.** A change ships only
  after a 30-row slice shows ≥3pp at non-overlapping CIs **and** a
  fresh n=148 confirms.

## Implementation Approach

Each phase below:

1. Lands as multiple small commits (per
   `feedback_commit_granularity` memory).
2. Has automated + manual success criteria.
3. Has a **headline-cell mapping**: which cell, predicted delta,
   stage-level mechanism, falsifiability slice.
4. Appends to `.claude/memory/project_changelog.md` when shipped.

---

## Phase 0 — Reproduce baseline (Task #2)

### Overview

Confirm `harness-60plus-iteration` reproduces the main-stack 49.3%
result before iterating. Single fresh n=148 run. **Headline cell
mapping**: this phase is a sanity gate, not a cell-mover.

### Changes Required

None to code. Just a fresh eval run.

### Commands

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --hf-split validation \
  --output-dir results/hf/sprint-2026-05-13/60plus-baseline-run1/
```

### Success Criteria

**Automated:**

- [ ] Run completes (148/148 examples scored, no resume gaps).
- [ ] Overall accuracy lands in **[47.0%, 51.5%]** (within the
      variance floor around the 49.3% main-stack number).
- [ ] `page_recall ≥ 0.83`, `bbox_iou ≥ 0.77` (no layout drift).
- [ ] Tier sha matches `333fe987` (no accidental config change).

**Manual:**

- [ ] `cat results/hf/sprint-2026-05-13/60plus-baseline-run1/focusparse_focus_agentic_multi_page_*.json | jq .overall`
      compares directly to the main-stack number.
- [ ] If reproducer is **out of band**, stop and diagnose (likely
      causes: Modal endpoint outage, layout cache miss, tier override).

### Falsifiability

If we cannot reproduce the baseline, every subsequent A/B is suspect.
Hard gate.

---

## Phase 1 — Failure-mode triage (Task #3)

### Overview

Bucket every wrong example. This is the single highest-information
artifact in the sprint — it dictates iteration order in Phase 3.

**Headline cell mapping:** N/A (diagnostic phase).

### Changes Required

#### 1. Run the existing diagnoser

`scripts/diagnose_predictions.py` already mines per-example
predictions for tool-error rates, lazy-answer rates, iteration
histograms.

```bash
uv run python scripts/diagnose_predictions.py \
  --spec-dir results/hf/sprint-2026-05-13/60plus-baseline-run1/ \
  --output results/diagnostics/60plus-baseline-run1/report.md
```

#### 2. Manual per-example bucketing

For each row with `answer_correct == 0.0`:

1. Read `per_example.jsonl` for the row.
2. Inspect `predictions/<example_id>.json` (full pipeline trace).
3. Open the source image / page via `tiles/` or NFS hydrate
   (`focusparse.dataset.nfs.rsync_pull(doc_id)`).
4. Assign exactly one bucket:
   - `bad_layout` — primary layout box does not contain the answer span
     or is the full-page stub. (Page is right, bbox is wrong.)
   - `wrong_page` — `page_recall == 0`. The router pointed somewhere
     else entirely.
   - `wrong_extraction` — IoU≥0.3, page_recall≥0.5, but the reasoner
     extracted a wrong / misformatted value from the right region.
   - `verifier_rejected_correct` — reasoner first answer matches gold
     by scorer, verifier rejected and retry produced a worse answer.
   - `tool_missed` — `chart_to_table` / `expand_context` / `run_python`
     would have provided the missing evidence, but the tool wasn't
     selected.
   - `lazy_abstain` — predicted "Unanswerable" while gold is non-null
     and evidence is present in the packets.

Output table at `thoughts/shared/audits/2026-05-13-failure-triage.md`:

```markdown
| example_id   | domain    | bucket           | rationale (one line)                                          | candidate fix                  |
| ------------ | --------- | ---------------- | ------------------------------------------------------------- | ------------------------------ |
| dat-foo-0001 | datasheet | wrong_extraction | gold "180,683; typical", pred "Gross margin 180,683, typical" | label-prefix strip in reasoner |

...
```

### Success Criteria

**Automated:**

- [ ] Diagnoser report exists at
      `results/diagnostics/60plus-baseline-run1/report.md`.

**Manual:**

- [ ] Every `answer_correct == 0.0` row in the baseline has a bucket
      label and a one-line rationale.
- [ ] Bucket counts add to (148 − #correct).
- [ ] Per-domain bucket distribution is summarized at the top of the
      triage file (datasheet vs finance is the key cut).

### Falsifiability

If `wrong_extraction` is **not** the largest bucket, the
2026-05-11 "81% of failures are post-localization" prior is wrong on
this baseline and the iteration order in Phase 3 needs reconsideration.

---

## Phase 2 — Golden audit on failure set (Task #4)

### Overview

For each row in the failure-triage file, decide whether the harness or
the benchmark owes the answer. Builds the **gold-fix backlog** and
removes noise from the iteration target.

**Headline cell mapping:** N/A (diagnostic phase, but golden_incorrect
rows reduce the denominator we're iterating against).

### Changes Required

#### 1. Run the existing parser-bench golden auditor on the failure set

```bash
uv run python scripts/audit_parser_bench_goldens.py \
  --hf-revision <pinned-revision> \
  --splits validation \
  --only-ids "$(jq -r '.failure_ids[]' results/diagnostics/60plus-baseline-run1/summary.json | paste -sd,)" \
  --output results/audits/60plus-golden-audit/
```

(If `--only-ids` is not yet supported in the auditor, add the flag —
single-file change in `scripts/audit_parser_bench_goldens.py`.)

#### 2. Manual verdict pass

For each failure row, compare the predicted answer, the gold answer,
and the source document. Assign one of:

- `harness_error` — gold is correct and unambiguous; harness produced
  a wrong or lazy answer. (Counts against us.)
- `unanswerable` — the document genuinely does not contain a
  determinate answer. Gold should be `Unanswerable` or the question
  should be revised. (Upstream fix candidate.)
- `golden_incorrect` — gold answer is demonstrably wrong (typo, wrong
  page, wrong unit). (Upstream fix candidate.)
- `ambiguous` — multiple reasonable answers exist or the question's
  scope is unclear. (Counts against us partially; track separately
  but address via prompt-precision experiments.)

Output table at `thoughts/shared/audits/2026-05-13-golden-audit.md`:

```markdown
| example_id        | domain  | bucket (from Phase 1) | verdict      | rationale                            | upstream-fix?                       |
| ----------------- | ------- | --------------------- | ------------ | ------------------------------------ | ----------------------------------- |
| fin-cad-2021-0014 | finance | lazy_abstain          | unanswerable | doc shows "TBD" in the relevant cell | yes — switch gold to "Unanswerable" |

...
```

#### 3. Effective denominator

Compute `effective_n = 148 − count(golden_incorrect) − count(unanswerable_with_non-null_gold)`.
Track both raw and effective accuracy. Headline target is 60%+ on
**raw** n=148; the effective number is reported for context.

### Success Criteria

**Automated:**

- [ ] `thoughts/shared/audits/2026-05-13-golden-audit.md` exists with a
      verdict per failure-set row.
- [ ] Verdict counts sum to the failure-set size.

**Manual:**

- [ ] Upstream-fix candidates are itemized and ready to PR against
      parser-bench (separate PR, **not** in this repo).
- [ ] No row is left unverdicted; `ambiguous` is the only soft bucket.

### Falsifiability

If `harness_error` is < 50% of failures (i.e., the benchmark has more
problems than the model), revisit whether 60% is the right target on
this revision — push for a fresh parser-bench revision with the
upstream fixes applied before declaring victory.

---

## Phase 3 — Iterate the harness (Task #5)

### Overview

The mainline iteration loop. Each lever below has its own headline-cell
mapping and mechanism. **Implement in order of EV** (predicted-pp /
implementation-time): 3a → 3b → 3c → 3d → 3e → 3f.

After each lever ships:

1. A/B on a 30-row slice using the cache (`--llm-cache-dir
cache/llm_responses/<lever-name> --llm-cache-mode record-or-replay`).
2. If slice delta ≥ 3pp at non-overlapping CIs, promote to n=148.
3. If n=148 confirms, ship to default and rerun the next lever.
4. If n=148 contradicts the slice, save under
   `configs/experiments/<lever-name>.yaml` and document a negative
   result in `.claude/memory/MEMORY.md`.

### Phase 3a — Per-domain reasoner format-hint routing

**EV:** highest. Predicted +3 to +5pp overall, mostly on finance.

**Cell:** `Our harness +4 / Finance / accuracy` from 40.9% → ~50%.
`Our harness +4 / Datasheets / accuracy` stays at ~56.7% or rises.

**Mechanism:** the Phase 6a `exact_match` prompt tightening helps
datasheets (their answer spans are short identifiers / labels) and
hurts finance (their answers often require unit normalization and
multi-part values that the rule "Output ONLY the answer span" can
truncate).

**Changes required:**

- `src/focusparse/pipeline/reasoner.py:83` (`_format_hint`):
  accept `domain: str | None` and `question_family: str | None`. Branch
  the `exact_match` branch on domain:
  - `datasheet`: keep the 4-rule strict prompt (current behavior).
  - `finance`: relax rules 1 and 2 (allow trailing units like "%",
    "$", "millions", and label-prefix when the gold includes it).
    Keep rules 3 and 4.
  - `None`: keep current behavior as fallback.
- Pipe `question.domain` from `answer_from_evidence` (`reasoner.py:147`)
  through to `_format_hint`. `QuestionEvent.domain` already exists.
- Add a small lookup table for `question_family`-specific hints (e.g.
  `register_bit_field` keeps the bracket-and-bit-field rule from the
  current prompt; `curve_axis_reading` adds a "interpolate to nearest
  axis gridline" nudge).
- Tests: `tests/test_reasoner.py` — add cases for each
  (domain, question_family) branch verifying the prompt text contains
  the expected rule signature.

**Success criteria:**

- [ ] Slice A/B (30 finance + 30 datasheet rows): finance delta ≥ +5pp,
      datasheet delta ≥ −1pp. Cost neutral.
- [ ] n=148 confirms: ≥ +3pp overall, finance ≥ +6pp, datasheet not
      regressed beyond −2pp.

### Phase 3b — Reasoner self-consistency on wrong_extraction

**EV:** medium-high. Predicted +2 to +3pp on the ~43 `wrong_extraction`
rows. Doubles reasoner cost (still well within budget).

**Cell:** `Our harness +4 / Datasheets / accuracy` primarily (datasheets
have most of the long-tail extraction errors).

**Mechanism:** K=2 samples from the reasoner (temperature staggered or
prompt-variant staggered); pick the more concise / higher-confidence
answer using a structured scorer (shorter answer, exact-match-shape
match, higher self-confidence).

**Changes required:**

- `src/focusparse/pipeline/reasoner.py` — add `answer_from_evidence_k`
  that returns `list[(AnswerEvent, ModelResponse)]` for K=2.
- `src/focusparse/pipeline/workflow.py` — wire a
  `reasoner_self_consistency` config flag; default off, enable for
  this experiment. When on, call the K-variant, pick the best, attribute
  the cost of both samples to the run.
- Picker: prefer (a) shorter answer, (b) higher answer confidence,
  (c) higher overlap with reasoner-supported citation packets. Tie
  break by sample index 0.
- Tests: deterministic picker tests with synthetic AnswerEvent pairs.

**Success criteria:**

- [ ] Slice A/B (30 wrong_extraction rows from Phase 1): ≥ +2pp.
- [ ] n=148 confirms: ≥ +2pp overall at ≤ 2× reasoner cost.

### Phase 3c — Tool-selection gates for tool_missed bucket

**EV:** medium. Predicted +1 to +2pp on the `tool_missed` rows.

**Cell:** `Our harness +4 / Finance / accuracy` primarily (charts are
finance-heavy).

**Mechanism:** the gates in
`src/focusparse/pipeline/workflow.py:91-128` (`_should_use_react_inspector`)
and the `_run_expand` dynamic initial-expand gate already exist. Extend:

- `chart_to_table` is gated on `figure_class ∈ chart_classes`; verify
  the gate fires whenever the planner sets `question_family ∈
{curve_axis_reading, chart_value_lookup}` and a chart-class region
  is reranked into the top-K. Add a fallback firing rule: if the
  primary region's `figure_class == "other"` but the question family
  demands a chart, attempt `chart_to_table` with `figure_class="chart"`
  as a hint to the LLM extractor.
- `expand_context` should also fire when the verifier rejects an answer
  with `missing_context: ["table-header", "axis-label"]`. The current
  verifier-directed retry already triggers; verify it's matching the
  family-keyword variants from `_neighbor_types_from_verifier_reason`.

**Changes required:**

- `src/focusparse/pipeline/inspector.py:707-720` (`_figure_class`
  override hint) — accept `question_family` and prefer `"chart"` when
  the family demands chart-grounded evidence.
- `src/focusparse/pipeline/verifier.py:466` (`_normalize_missing_context_values`)
  — expand the synonym map to cover finance-specific phrasings
  ("category label", "row label", "header cell").
- Tests: snapshot the gate firing rates on the failure-set
  `tool_missed` rows.

**Success criteria:**

- [ ] On `tool_missed` rows in the triage file, the new gate fires
      `chart_to_table` / `expand_context` for ≥ 70% of them.
- [ ] n=148 confirms: ≥ +1pp overall, finance ≥ +2pp.

### Phase 3d — Verifier abstain-routing

**EV:** medium-low. Predicted +0.5 to +1pp on `lazy_abstain` and
`verifier_rejected_correct` buckets combined.

**Cell:** `Our harness +4 / both / accuracy`. Also moves
`lazy_answer_rate` toward baseline.

**Mechanism:** the verifier sometimes rejects a correct first-pass
answer and the retry produces a worse one or an "Unanswerable". Two
small policy changes:

1. When `verifier_rejected_correct` (per-triage), do **not** clobber the
   first answer with the retry if the retry is "Unanswerable" and the
   first was non-null and packet-cited.
2. When the reasoner's first answer is "Unanswerable" but ≥ 2 packets
   were cited and `evidence_reward ≥ 0.5`, force one retry with a
   "the evidence supports an answer; do not abstain unless cells are
   genuinely missing" hint. This is a narrow lever — only fires when
   the verifier disagrees with the abstention.

**Changes required:**

- `src/focusparse/pipeline/workflow.py` — guard the
  "answer recovery after retry" block (`_focused_retry_evidence`,
  `_is_better_unsupported_answer`) so a non-null packet-cited first
  answer survives a worse retry.
- `src/focusparse/pipeline/verifier.py:122` (`verify_answer`) — add a
  "abstain-with-evidence" verdict path that triggers the narrow retry
  hint above.
- Tests: workflow regression tests for both cases with synthetic
  AnswerEvents.

**Success criteria:**

- [ ] `lazy_answer_rate` drops by ≥ 1pp on n=148.
- [ ] No regression in datasheet or finance accuracy on the slice.

### Phase 3e — Bbox + crop quality refinement

**EV:** low-medium. Predicted +0.5 to +1.5pp on `bad_layout` rows
(usually a single-digit count).

**Cell:** `Our harness +4 / both / accuracy`. Marginal lift on
`bbox_iou` for borderline cases.

**Mechanism:** the localizer rerank
(`src/focusparse/pipeline/localizer.py:56`) picks the top-K boxes from
the Modal layout endpoint. Some failure rows show the top-K box
slightly under-sized — answer spans clipped by the right or bottom edge.
Padding policy currently lives at `expander.py:1170` (`_pad_bbox`).

**Changes required:**

- `src/focusparse/pipeline/expander.py:1170` (`_pad_bbox`) — increase
  padding when the figure_class is `table` and the bbox edge is within
  5% of the page edge (catch clipped column headers / row footers).
- `src/focusparse/pipeline/localizer.py:152` (`_detect_for_page`) —
  log when the layout endpoint returns a full-page stub for a question
  where the planner expected `evidence_types: ["table"]` so we can
  see how often it happens.
- `src/focusparse/tools/layout_detect.py` already raises on stub;
  verify the raise propagates to a skeleton-region path that the
  workflow handles gracefully.
- Tests: `tests/test_expander.py` — case for the new padding policy.

**Success criteria:**

- [ ] `bbox_iou` on `bad_layout` rows in triage rises by ≥ 5pp.
- [ ] No `bbox_iou` regression overall.

### Phase 3f — Pre-localizer page routing improvements

**EV:** low. Predicted +0 to +1pp on `wrong_page` rows (usually
a small count).

**Cell:** `Our harness +4 / both / accuracy`. Marginal.

**Mechanism:** `src/focusparse/pipeline/router.py:39` (`route_pages`)
uses FTS5/BM25 over the text layer. Two micro-fixes:

1. When a question contains a register name (`HSCTRL`, `VCSR0`), BM25
   often points at the register's intro page but misses the
   bit-field-encoding page that lives 1-3 pages later. Add a
   adjacency-window expansion: when the top-1 page has a register-class
   reference, include the next 1-2 pages in the routed list.
2. When the planner classifies `question_family == "table_lookup"` and
   the top-K text-FTS pages don't contain a table layout box, fall
   back to a layout-FTS join (first page with a table layout box that
   shares ≥ 1 question token).

**Changes required:**

- `src/focusparse/pipeline/router.py:39` — implement the two
  micro-rules above.
- Tests: `tests/test_router.py` — register-adjacency and
  table-lookup-fallback cases.

**Success criteria:**

- [ ] `page_recall` on `wrong_page` rows rises by ≥ 20pp.
- [ ] `page_recall` overall does not regress.

### Phase 3 success criteria (aggregate)

- [ ] After each lever ships, append a one-line entry to
      `.claude/memory/project_changelog.md` with cell, mechanism, and
      delta.
- [ ] After 3a–3c land (the high-EV stack), run a fresh n=148.
- [ ] If overall ≥ 58%, stop; do one more lever (the cheapest remaining)
      and target 60%+.
- [ ] If overall < 58% after 3a–3c, audit the failure-triage table
      against the actual failure pattern; some buckets may have grown.

---

## Phase 4 — Final n=148 gate (Task #6)

### Overview

Single clean run on the final stack. **No further code changes
between this run and the artifact writeup.** This is the publishable
number.

### Commands

```bash
uv run python scripts/run_hf_eval.py --agent focus \
  --protocol agentic_multi_page --hf-split validation \
  --output-dir results/hf/sprint-2026-05-13/60plus-final-run1/
```

### Success Criteria

**Automated:**

- [ ] Overall accuracy ≥ 60.0%.
- [ ] `lazy_answer_rate ≤ baseline + 1pp` (i.e., ≤ 9.1%).
- [ ] `bbox_iou ≥ 0.77` (no more than 2pp drop from baseline).
- [ ] Cost per correct ≤ $0.04.

**Manual:**

- [ ] Variance replication: rerun with `--llm-cache-dir
    cache/llm_responses/60plus-final-replica
    --llm-cache-mode record-or-replay` to confirm the win is not a
      single-run flutter (planner + localizer_rerank are replayed; only
      reasoner + verifier vary).
- [ ] `docs/research/2026-05-13-harness-60plus-results.md` documents the
      stack with per-phase deltas + headline cell mapping.

### Falsifiability / Off-ramps

- **If overall lands in [55%, 60%):** add one more high-EV lever from
  the failure triage (the largest remaining bucket) and rerun. If still
  short after a second attempt, document the ceiling and ship the best
  result as an opt-in flag.
- **If overall lands in [50%, 55%):** the failure-mode prior was
  miscalibrated; restart Phase 1 against the post-Phase-3 wrong set
  and pick a different lever.
- **If overall regresses below 49.3%:** roll back to baseline; we have
  a stack-interaction bug, not a model gap. Investigate
  `cited_evidence_completeness` and `verifier_abstain_rate` first.

---

## Cost Budget

User-confirmed: **~$100+** for the full iteration.

Estimated cost breakdown:

| Item                      | Count | $/each | Subtotal |
| ------------------------- | ----- | ------ | -------- |
| n=148 baseline reproducer | 1     | $5     | $5       |
| n=148 after Phase 3a      | 1     | $5     | $5       |
| n=148 after Phase 3b      | 1     | $7     | $7       |
| n=148 after Phase 3c      | 1     | $5     | $5       |
| n=148 after Phase 3d      | 1     | $5     | $5       |
| n=148 final + replica     | 2     | $5     | $10      |
| 30-row slice A/Bs         | ~15   | $0.50  | $7.50    |
| Smoke / debug runs        | ~10   | $0.30  | $3       |
| Buffer                    | —     | —      | $50      |
| **Total**                 |       |        | **≈$98** |

The slice-first protocol keeps per-experiment cost <$1 in 90% of
cases. Reasoner + verifier never cached → cost is real on every run
even when planner/localizer are replayed.

---

## Risks & Mitigations

| Risk                                                                   | Mitigation                                                                               |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Per-domain prompt routing overfits finance and breaks datasheet        | Slice-first A/B on both domains in parallel; gate datasheet regression at ≤ 2pp          |
| Self-consistency doubles cost without lifting accuracy                 | Implement behind config flag; off if slice delta < +2pp                                  |
| Bucket triage is too subjective                                        | Two-pass labelling — first pass by a reviewer agent, second pass cross-check by us       |
| Modal layout endpoint outage during a critical eval                    | Use `--skip-layout-preflight` only as last resort; otherwise pause and resume            |
| Codex's `codex/harness-60-accuracy` ships compact-answer changes first | Cherry-pick after their changes land on main if they survive their own A/B               |
| Hitting 60% on a benchmark with golden-incorrect rows                  | Track effective n separately; if raw ≥ 60% is gated by gold errors, file the upstream PR |

---

## Open Questions

- Do we want to record full reasoner traces under
  `record-or-replay` for the final run so the SFT trajectory exporter
  picks them up? (Default: yes — the schema is at `schema_version=1`
  and these are high-quality teacher trajectories.)
- Is `chart_to_table` LLM extraction (Phase 7) being used as advertised
  on n=148 (97/148 = 66% populated)? Phase 3c assumes yes; we'll verify
  during triage.

---

## What This Plan Subordinates

This plan does **not** replace
`plans/2026-04-29-research-driven-eval-framework.md`. It is an
**execution arm** of that plan's Phase 6 ("iterate harness post-table").
Every lever is a Phase-6 candidate that this plan promotes to
production after slice + n=148 confirmation.

Prior plans whose unchecked items get absorbed here:

- `plans/2026-04-27-phase2-sota-leverage.md` — items 3 (loop) and 4
  (rerank) inform Phases 3c and 3e.
- `plans/2026-05-06-path-a-plumb-neighbors-into-reasoner.md` — its
  follow-up on neighbor disclosure to the reasoner is a Phase 3b
  picker input.

---

## Stopping Condition

Mark Task #6 completed and write the result up at
`docs/research/2026-05-13-harness-60plus-results.md` when **all** of:

1. n=148 overall accuracy ≥ 60.0%.
2. `lazy_answer_rate ≤ baseline + 1pp`.
3. `bbox_iou ≥ baseline − 2pp`.
4. A replication run under `--llm-cache-mode record-or-replay`
   reproduces the result within ±2pp on the same cache seed.

Once stopping condition is hit, further work needs new direction from
the user — the autonomy contract is "until 60%+ or blocked," not
"until 75%+".
