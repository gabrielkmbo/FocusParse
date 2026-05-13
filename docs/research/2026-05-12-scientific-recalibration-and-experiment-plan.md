# FocusParse Scientific Recalibration And Experiment Plan

Date: 2026-05-12
Scope: inspection of `docs/research/2026-05-11-focusparse-pipeline-change-summary.md`,
the current implementation, canonical n=148 headline artifacts, and the latest
complete Focus-only sprint runs. This is a research memo, not a code-change plan.

## 0. Recalibrated Thesis

FocusParse should be framed as a formal methods comparison:

> A structured, query-conditioned, budget-aware evidence harness beats base VLMs
> and generic agentic baselines on high-resolution document parsing because it
> localizes, constructs, and verifies evidence before asking the reasoner to
> answer. The claim is about controlled evidence construction, not raw tool count.

The current evidence supports the harness-vs-generic-agent claim. It does not yet
prove every stronger version of the thesis, especially "FocusParse +4 tools is
strictly better than FocusParse +2 tools." That narrower tool-count claim needs a
matched replicated A/B under fixed upstream sampling.

## 1. Methods Currently Implemented

The headline comparison has seven rows:

| Method | Implementation | Tool access | Scientific purpose |
| --- | --- | --- | --- |
| Base VLM | `SimpleBaselineAgent` in `workflow.py` | none | Frontier reasoner with no harness. |
| ReAct +2 | `react_agent.py` | `inspect_region`, `get_text_layer` | Tests whether an open agent loop with the same tools is enough. |
| ReAct +4 | `react_agent.py` | + `expand_context`, `run_python` | Tests whether generic agents benefit from more tools. |
| Agent baseline +2 | `agent_baseline.py` | same +2 belt | Tests a thinner generic loop with weaker prompt discipline. |
| Agent baseline +4 | `agent_baseline.py` | same +4 belt | Tests tool count without FocusParse stage structure. |
| FocusParse +2 | `FocusWorkflow(tool_set="minimal")` | `inspect_region`, `get_text_layer` | Harness without context expansion or `run_python`. |
| FocusParse +4 | `FocusWorkflow(tool_set="full")` | + `expand_context`, `run_python` | Full evidence-construction harness. |

The load-bearing FocusParse method is:

```text
plan -> route_pages -> localize -> rerank -> inspect -> expand_context -> answer -> verify
```

Key contracts and signals:

- `EvidencePacket` is the reasoner boundary. The reasoner sees packets, not raw
  pages.
- `tool_set="minimal"` skips `expand_context` and disables `run_python`; this
  makes +2 vs +4 a real ablation.
- `tool_set="full"` exposes `expand_context` and `run_python`; current branch
  also exposes `chart_to_table` when the flag is enabled.
- Recent branch state includes hard-case `react_inspector` dispatch,
  `chart_to_table` gate expansion, expander role weighting, and LLM response
  caching infrastructure.

## 2. Canonical Quantitative Result

Source artifacts:

- `results/hf/headline-v1-rebaseline-v2/headline_table.json`
- `results/hf/headline-v1-rebaseline-v2/*/per_example.jsonl`
- `results/diagnostics/rebaseline-v2/report.md`

These are the cleanest all-method n=148 comparison artifacts in the current
checkout. Cost is the recorded run cost computed from `src/focusparse/eval/pricing.py`
using the repo's 2026-04 list-price table. Treat it as experimental cost, not a
freshly refreshed provider rate card.

| Method | Accuracy | 95% CI | Cost/correct | Mean latency | Mean bbox IoU | Page recall | Lazy rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Base VLM | 37.8% | [30.4, 46.6] | $0.0119 | 3.01s | 6.1% | 83.8% | 100.0% |
| ReAct +2 | 13.5% | [7.4, 18.9] | $0.1846 | 16.15s | 31.8% | 78.2% | 19.6% |
| ReAct +4 | 14.2% | [8.8, 20.9] | $0.2403 | 21.11s | 29.3% | 75.0% | 24.3% |
| Agent baseline +2 | 8.1% | [4.1, 12.8] | $0.1244 | 5.42s | 0.0% | 0.0% | 100.0% |
| Agent baseline +4 | 6.8% | [2.7, 10.8] | $0.1535 | 5.82s | 0.0% | 0.0% | 100.0% |
| FocusParse +2 | 50.0% | [42.6, 57.4] | $0.0153 | 2.52s | 70.8% | 80.4% | 9.5% |
| FocusParse +4 | 43.9% | [36.5, 51.4] | $0.0176 | 2.53s | 66.1% | 76.9% | 11.5% |

### Reading The Table

Supported:

- The harness beats Base VLM overall in both Focus rows: +12.2 pp for +2 and
  +6.1 pp for +4.
- The harness beats ReAct by a large margin with the same tool-count axis:
  +36.5 pp at +2 and +29.7 pp at +4.
- Generic +4 tools do not help. ReAct +4 is only +0.7 pp over ReAct +2 while
  costing more and taking longer; Agent baseline +4 is worse than Agent +2.
- Region evidence quality is the clearest mechanism signal: FocusParse IoU is
  66-71%, ReAct is about 29-32%, Base VLM is about 6%, and Agent baseline is 0%.

Not yet supported:

- Canonical FocusParse +4 is not better than canonical FocusParse +2. The +4 row
  is -6.1 pp overall in `headline-v1-rebaseline-v2`.
- The current +4 story is therefore not "more tools are better." It is "tools
  help only when the harness constrains their selection and evidence insertion."

## 3. Latest Complete Focus-Only Runs

The newest complete Focus-only runs are:

- `results/hf/sprint-2026-05-11/phase4-run1/`
- `results/hf/sprint-2026-05-11/phase5-run1/`

Both runs use `tool_set="full"` with `chart_to_table_enabled=true` and
`use_react_inspector=true`. Their artifact suffix is `333fe987`, which the
newer `run.json` identifies as `tier_sha8`, not a pinned HF dataset revision.
`hf_revision` is still `null`; the dataset fingerprint is `835d8b90da8f7c1a`.

| Run | Accuracy | Datasheet | Finance | Cost/correct | Mean latency | Bbox IoU | Page recall | Lazy rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| phase4-run1 | 48.0% | 52.5% | 43.2% | $0.0249 | 3.65s | 84.1% | 88.1% | 7.4% |
| phase5-run1 | 45.3% | 50.5% | 41.9% | $0.0266 | 3.53s | 76.1% | 85.7% | 9.5% |
| Mean | 46.6% | 51.5% | 42.5% | $0.0257 | 3.59s | 80.1% | 86.9% | 8.5% |

`phase6a-run1` has 115 prediction JSON files but no `run.json` or
`per_example.jsonl`, so it should be treated as incomplete and excluded from
claims.

### Latest-Run Interpretation

The recent full-stack branch increases the mechanism signal:

- Bbox IoU improves from canonical Focus +4's 66.1% to 76.1-84.1%.
- Finance accuracy improves from canonical Focus +4's 31.9% to 41.9-43.2%.
- Lazy rate drops from 11.5% to 7.4-9.5%.

But the latest runs do not yet produce the target >=55% integration result. They
are directional evidence that harder evidence construction is working, especially
in finance, but they also raise cost/correct from $0.0176 to about $0.025-0.027
and latency from 2.5s to about 3.6s.

## 4. Mechanism Signals

From `results/hf/sprint-2026-05-11/phase4-run1/diagnostics.md`:

| Mechanism metric | Value |
| --- | ---: |
| Accuracy | 48.0% |
| Verifier unsupported rate | 62.9% |
| Retry used rate | 43.9% |
| Loop retry helped count | 6 true / 59 false |
| `expand_context_called_rate` | 96.6% |
| Mean neighbors attached | 9.61 |
| Mean new neighbors | 7.12 |
| Mean useful tool calls | 1.09 |
| Mean irrelevant tool calls | 1.27 |
| Answer changed after tool | 10.5% |
| Verifier supported after tool | 9.4% |
| Cited packet text coverage | 100.0% |
| Cited packet linked-context rate | 85.7% |
| Cited image-only rate | 0.0% |
| `chart_to_table` attempt rate | 10.5% |
| Cited packet chart rate | 0.0% |

Interpretation:

- Evidence packets are much healthier than before Path A: cited packets are not
  image-only, and linked context usually reaches cited evidence.
- The expander is still too noisy. Irrelevant tool-call proxy mean remains higher
  than useful tool-call proxy mean.
- `chart_to_table` is attempting work but is not yet producing cited chart
  evidence. That makes the chart tool an instrumentation target before it is a
  claim target.
- The verifier is finding many unsupported answers, but current retries rarely
  rescue them. The next improvement should make retries more selective and more
  likely to change support status.

## 5. Qualitative Examples Supporting The Thesis

Examples below come from the canonical seven-row comparison and the staged
benchmark file at `~/.cache/focusparse/hf_staging/benchmark.jsonl`. They are
chosen because FocusParse +4 is correct while Base VLM, ReAct +4, and Agent
baseline +4 are wrong under the scorer.

### 5.1 Visual distractor, datasheet layout

Example: `dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0052`

Question: In subfigure (b), one MOSFET is annotated `Q1 (HS)` and the other
`Q2 (LS)`. Which MOSFET is positioned at the top of the package layout,
adjacent to the row of large blue output capacitors?

Gold: `Q1 (HS)`

| Method | Prediction | Correct |
| --- | --- | --- |
| Base VLM | `Q2 (LS)` | no |
| ReAct +4 | says the phase node is associated with Q2 | no |
| Agent baseline +4 | says Q2 | no |
| FocusParse +4 | `Q1 (HS)` | yes |

Mechanism: the harness localizes the relevant subfigure and treats the visual
layout as the evidence unit. The generic agents reason from the functional
"phase node" relationship and drift to the wrong MOSFET.

### 5.2 Finance chart axis reading

Example: `fin-boe_fsr_2024_jun-0007`

Question: At `End-28`, what is the approximate difference in cumulative share
between leveraged loans and investment-grade bonds maturing?

Gold: `40`

| Method | Prediction | Correct |
| --- | --- | --- |
| Base VLM | `20` | no |
| ReAct +4 | answers about end-2026, about 25 pp | no |
| Agent baseline +4 | about 20 pp | no |
| FocusParse +4 | `40%` | yes |

Mechanism: FocusParse cites the correct chart region with bbox IoU 1.0 and
returns the short numeric answer. The comparators either read the wrong x-axis
category or interpolate from the wrong series pair.

### 5.3 Spatial team-chart lookup

Example: `fin-jpm_gtm_us_daily-0018`

Question: On the Global Market Insights Strategy team page, identify the
New York-based team member whose portrait sits immediately above Samantha Azzarello
and to the left of Jordan Jackson.

Gold: `Stephanie Aliaga`

| Method | Prediction | Correct |
| --- | --- | --- |
| Base VLM | `Dr. David Kelly, CFA` | no |
| ReAct +4 | `Dr. David Kelly, CFA` | no |
| Agent baseline +4 | `Dr. David Kelly, CFA` | no |
| FocusParse +4 | `Stephanie Aliaga` | yes |

Mechanism: this is a spatial layout lookup where the answer is not the most
salient person on the page. The harness's region-first evidence selection avoids
the global salience trap that catches the base and generic-agent rows.

### 5.4 Exact-output caveat

Several Focus wins are scorer wins where a generic agent is semantically close
but fails exact-answer discipline. Example: `fin-vis-jpm_gtm_us_daily-0126`,
where ReAct says "UK has the highest USD yield..." but the benchmark answer is
the canonical string `UK`. This still matters for the benchmark because the task
requires exact extraction, but the paper should separate "semantic failure" from
"format failure" in qualitative analysis.

## 6. Research Claims: Status

| Claim | Current status | Evidence |
| --- | --- | --- |
| Structured harness beats base and generic agents | Supported directionally and quantitatively | Focus +2/+4 exceed Base, ReAct, and Agent baseline on n=148. |
| Tool count alone is not the win | Supported | Generic +4 is slower and more expensive, with no meaningful accuracy gain. |
| Evidence localization is the mechanism | Strong mechanism evidence | Focus IoU 66-84% vs ReAct about 30%; cited image-only rate is 0% in latest diagnostics. |
| Focus +4 beats Focus +2 | Not yet supported | Canonical +4 trails +2; latest +4 branch improves finance/IoU but needs matched +2 rerun. |
| `chart_to_table` improves finance | Not yet supported | Attempt rate is nonzero, but cited chart rate is still 0%. |
| Hard-case `react_inspector` helps | Open | Selected in 51/148 phase4 cases, but needs same-slice deterministic baseline comparison. |

## 7. Next Scientific Moves

1. Pin the comparison substrate.

   Record the exact HF dataset revision or at least the dataset fingerprint in
   every headline table. Do not call `7d4b816d` a dataset revision unless the
   run artifact says it is one; in newer artifacts it is explicitly a tier hash.

2. Treat phase4-run1 and phase5-run1 as exploratory complete replicates, not a
   final integration result.

   They show a real finance/IoU improvement but do not clear the target and were
   not rolled into a seven-row matched table.

3. Run a matched Focus +2 vs Focus +4 A/B on the current branch.

   This is the next most important experiment. It directly tests whether the
   current full tool belt is net positive after Path A, chart gating, hard-case
   inspector dispatch, and expander role gating.

4. Run the full seven-row table only after the Focus +4 mechanism is positive.

   Comparator rows are expensive and already frozen. Spend first on proving the
   harness delta, then refresh the full table.

5. Add slice diagnostics before claiming a phase win.

   Required slices:
   - finance vs datasheet
   - chart families vs non-chart families
   - `react_inspector` path vs deterministic inspector path
   - examples with `expand_context` retry vs no retry
   - exact-format failures vs semantic failures

6. Make the next paper claim narrower and stronger.

   Best current paper-shaped wording:

   > FocusParse's structured evidence harness improves accuracy and localization
   > over base VLM and generic agentic tool-use baselines. The advantage is not
   > explained by giving an agent more tools; it appears when a harness controls
   > evidence localization, context attachment, exact-answer formatting, and
   > verifier-directed repair.

## 8. Proposed Experiment Queue

### Experiment A: Current-branch Focus +2/+4 matched A/B

Question: does current +4 beat current +2 under the same code, config, and dataset?

Run:

```bash
uv run python scripts/run_hf_eval.py --agent focus --tool-set minimal \
  --protocol agentic_multi_page \
  --output-dir results/hf/sprint-2026-05-12/current-minimal-run1 \
  --staging-dir ~/.cache/focusparse/hf_staging \
  --pdfs-root ~/.cache/focusparse/pdfs

uv run python scripts/run_hf_eval.py --agent focus --tool-set full \
  --protocol agentic_multi_page --chart-to-table --use-react-inspector \
  --output-dir results/hf/sprint-2026-05-12/current-full-run1 \
  --staging-dir ~/.cache/focusparse/hf_staging \
  --pdfs-root ~/.cache/focusparse/pdfs
```

Decision gate: ship +4 defaults only if overall accuracy is at least +3 pp with
non-overlap or if finance improves at least +5 pp with no overall regression.

### Experiment B: Hard-case inspector slice

Question: is `react_inspector` actually helping the cases it touches?

Compare current full run against a full run with hard-case inspector disabled.
Report:

- `inspector_path == "react_hard_case"` rate
- hard-case slice accuracy
- hard-case verifier unsupported rate
- cost and latency delta on hard-case examples

### Experiment C: Expander noise reduction

Question: can we lower irrelevant context without losing cited-context coverage?

Gate:

- `mean_irrelevant_tool_call_count < mean_useful_tool_call_count`
- cited packet linked-context rate stays >=80%
- accuracy non-regressing within 3 pp

### Experiment D: `chart_to_table` usefulness

Question: does chart extraction produce cited machine-readable evidence?

Gate:

- chart attempt rate on chart families increases
- `cited_packet_chart_rate` becomes nonzero
- finance chart-family accuracy improves
- no empty-CSV prompt contamination on non-chart examples

## 9. Bottom Line

The project is already scientific enough to support a careful first claim:
FocusParse's structured evidence harness beats generic tool-use agents and base
VLM prompting on this n=148 benchmark, with much better localization and much
lower latency than ReAct. The next work should not add more features. It should
convert the latest mechanism improvements into matched, replicated A/B evidence,
especially on Focus +2 vs Focus +4 and on finance chart/table examples.
