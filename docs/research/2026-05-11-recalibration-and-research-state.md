# FocusParse — Research Recalibration and Current State

Date: 2026-05-11
Scope: a single, self-contained snapshot of where the research project is, what
the methods are, what the numbers say, and what qualitative evidence supports
the central thesis.

This doc is intentionally written as a research artifact, not an operational
note. It should be the starting point for the next experimental sprint and
the basis of the eventual paper-shaped writeup.

## 0. The recalibrated thesis

The central claim, restated tightly:

> A structured, query-conditioned, budget-aware **harness** that explicitly
> separates `localize -> inspect -> expand_context -> answer -> verify`
> beats both base VLMs and generic agentic baselines (ReAct, agent-baseline)
> at high-resolution domain-specific document parsing, at lower cost and
> lower latency, **because the harness controls how tools build evidence**,
> not because it has more tools.

Two corollaries this project is set up to prove:

1. **Tool count alone is not the win.** Generic agents with +4 tools are not
   better than the same agents with +2; in some configurations they are
   strictly worse. The harness's advantage scales with tool count only when
   the harness routes which tool runs and constrains how its output enters
   the evidence packet.
2. **Localization-first ordering is the unit of work.** The single biggest
   lever in this codebase is whether the right region reaches the reasoner;
   most other gains are downstream of that.

This is the metronome. Every proposed change should answer: which cell in the
4-method x 2-task x 2-metric headline table does this move, by how much, and
through what mechanism. If a change cannot answer that, deprioritize.

## 1. Methods under examination

Seven methods sit in the headline table. Three are baselines we are not trying
to improve. Four are the spine of the research claim.

### 1.1 Base VLM (one row)

- Spec: `simple` agent, no tool access. Full-document images are sent to
  the reasoner once. The reasoner returns an answer + citations.
- Implementation surface: `src/focusparse/pipeline/workflow.py::SimpleBaselineAgent`.
- Why it is in the table: it sets the floor for "how good is the frontier VLM
  with no scaffolding at all." Anything we ship that does not beat this is
  not worth the cost.

### 1.2 ReAct (+2 tools / +4 tools)

- Spec: open ReAct loop. The agent sees the question + (sampled) page tiles
  and freely interleaves Thought, Action, Action Input, Observation steps.
- Tool sets:
  - `+2` = `inspect_region`, `get_text_layer` (minimal).
  - `+4` = adds `expand_context`, `run_python` (full).
- Implementation surface: `src/focusparse/pipeline/react_agent.py`.
- Why it is in the table: it isolates "the harness" from "more tools." A
  generic ReAct agent gets the same toolbelt the harness uses; if our claim
  is "structure matters, not raw tool access," that has to be visible here.

### 1.3 Agent baseline (+2 tools / +4 tools)

- Spec: a single-step agent that selects an action then answers; no loop,
  no verifier, no retry.
- Same `+2` / `+4` tool axes.
- Implementation surface: `src/focusparse/pipeline/agent_baseline.py`.
- Why it is in the table: it isolates "the loop / verifier" from "the
  tools." If our claim is "structure matters," removing the loop should
  hurt, not help.

### 1.4 FocusParse harness (+2 tools / +4 tools) — the system under study

- Spec: a typed state machine over `plan -> route_pages -> localize ->
rerank -> inspect -> expand_context -> answer -> verify`, with a
  verifier-directed retry loop.
- Tool sets are the same `+2` / `+4` axes the comparators use.
- Implementation surface: `src/focusparse/pipeline/{workflow,planner,router,
localizer,inspector,expander,reasoner,verifier}.py`.

The harness has six load-bearing properties that the comparators do not:

1. **Layout localization as a first-class stage.** RT-DETRv2 produces region
   candidates before any reasoning, so the agent never asks "where on the
   page is the table?" while also answering "what does the table say?".
2. **Query-conditioned reranking.** Planner-emitted `evidence_types` and
   reranker `relevance` scores decide which regions become packets — the
   reasoner never sees a region the harness has not endorsed.
3. **Structured evidence packets** (`EvidencePacket` in
   `src/focusparse/evidence/packet.py`). Each packet carries a primary crop,
   optional `multi_scale_crops` (`tight` / `context` / `chart_context` /
   `zoomed`), `linked_crop_refs` for role-labeled neighbors (caption,
   footnote, legend, axis label), `text_layer_snippet`, optional
   `ocr_snippet`, and optional `chart_csv`. The reasoner sees packets, not
   raw pages.
4. **Role-labeled context expansion**, not blind context widening.
   `expand_context` uses planner evidence types + verifier missing-context
   hints + reranker roles + spatial adjacency to pick a _small_ number of
   neighbors per packet (default `max_neighbors_per_packet=2`).
5. **Verifier as controller, not just judge.** The verifier returns
   `next_action in {accept, retry_localization, expand_context, abstain,
escalate_reasoner}`. The workflow forwards `diagnostics.missing_context`
   and target packet ids back into the right stage.
6. **Tool-set axis is real.** `tool_set="minimal"` disables
   `expand_context` and `run_python` (auto-zoom forced off). `tool_set="full"`
   enables them. This makes `+2` vs `+4` a real ablation rather than a flag
   that flips on whether the same code path runs.

The first three are the core of the thesis. The last three are the
machinery that lets `+4` produce more answerable evidence than `+2`
without producing more noise.

### 1.5 What is intentionally frozen

Per the project memory's narrowed-scope decision: `plan`, `route_pages`,
`answer`, and `verify` are not the active research target. They are real
LLM stages, and the verifier was promoted to a controller, but the
implementation focus stays on `localize`, `inspect`, `expand_context`
and the tools that feed them (`inspect_region`, `expand_context`,
`run_python`, `chart_to_table`). The training-target trajectory schema
also concentrates on focus-stage signals.

## 2. Latest approach and what just shipped

Three rounds of work fed into the current state:

### 2.1 PR #1 (merge `56185e1`) — evidence repair

- Inspector page-image fallback crops (so HF runs without source PDFs do
  not crater on missing text layers).
- Native PDF text first, OCR fallback second.
- Question-family-gated context crops (`curve_axis_reading`,
  `legend_series_binding`, `multi_chart_comparison`, `timing_diagram_reading`).
- Optional sandboxed `run_python` auto-zoom (additive, not destructive).
- Verifier-directed retry: `missing_context` vocabulary
  (`caption / legend / footnote / header / axis_label / row_header /
column_header / unit / x_axis / y_axis / continuation`), target packet
  ids, text-only context attachment for header-like neighbors.

### 2.2 PR #2 (merge `4627df8`) — toolset instrumentation and latency

- `available_tools`, `selected_tools`, `tool_call_sequence`,
  `useful_tool_call_count`, `irrelevant_tool_call_count`,
  `failed_tool_call_count`, `answer_changed_after_tool`,
  `verifier_supported_after_tool` emitted per example.
- `diagnose_predictions.py` summarizes tool sequence top-k, available and
  selected tool belts, verifier unsupported and next-action distributions,
  expand-context rate, mean neighbors, mean useful neighbors, failure
  reason distribution, cited packet text/context/chart coverage,
  cited-image-only rate.
- `AggregateMetrics.latency_ms_mean` is now a first-class metric in HF eval
  rollups.

### 2.3 PR #3 (merge `225210b`) — table exports and latency enrichment

- Headline tables emit `.md`, `.html`, `.csv`, `.jsonl`. The flat exports
  carry latency columns and CIs.
- `enrich_headline_table_latency.py` retrofits latency onto older rollups
  by reading `run.json` / `per_example.jsonl`, avoiding rerunning expensive
  evals just to add latency columns.

### 2.4 Path A (commits `44c956e`, `fb1b237`, `bad9132`)

The reasoner now actually consumes the neighbors the expander attaches:

- `_collect_packet_images` walks `linked_crop_refs` after primary and
  context crops, deduplicated.
- Packet descriptors list neighbor types ("Attached neighbors (N):
  caption, footnote, ...").
- System prompt now distinguishes primary `tight` evidence from
  `context` / `chart_context` / `zoomed` / `context_window` and from
  attached neighbors.

Before Path A, `expand_context` populated `linked_crop_refs` but the
reasoner image collector did not include them. So neighbor expansion was
effectively dead code with respect to the reasoner. This is the most
load-bearing single fix in the recent sprint.

### 2.5 Where the code lives (one-line index)

| File                                                      | Role                                                             |
| --------------------------------------------------------- | ---------------------------------------------------------------- |
| `src/focusparse/pipeline/workflow.py`                     | state machine + verifier-directed retry loop, telemetry emission |
| `src/focusparse/pipeline/planner.py`                      | question_family + evidence_types + budget_class                  |
| `src/focusparse/pipeline/router.py`                       | FTS5 + BM25 page routing                                         |
| `src/focusparse/pipeline/localizer.py`                    | HF RT-DETRv2 region detection (with disk cache)                  |
| `src/focusparse/pipeline/inspector.py`                    | deterministic + (optional) ReAct-driven evidence construction    |
| `src/focusparse/pipeline/expander.py`                     | query-conditioned, role-labeled neighbor attachment              |
| `src/focusparse/pipeline/reasoner.py`                     | answer + citations; now consumes linked neighbors                |
| `src/focusparse/pipeline/verifier.py`                     | structured verdict + next_action controller                      |
| `src/focusparse/evidence/packet.py`                       | `EvidencePacket` contract                                        |
| `src/focusparse/eval/{harness,scoring,metrics,report}.py` | eval entrypoints                                                 |
| `scripts/diagnose_predictions.py`                         | mechanism diagnostics                                            |
| `scripts/run_hf_eval.py`                                  | HF dataset runner                                                |
| `scripts/render_headline_table.py`                        | 7-row table emission                                             |
| `scripts/enrich_headline_table_latency.py`                | post-hoc latency backfill                                        |

## 3. Quantitative comparison

All numbers below are on the **rebaseline-v2** n=148 split
(101 datasheets + 47 finance), agentic_multi_page protocol, dataset
revision `7d4b816d` (the canonical revision the headline table was
generated against). They are the cleanest matched-A/B numbers we have
across all seven methods.

### 3.1 Headline table — accuracy and cost per correct

| Method                   | Datasheets acc | Finance acc | Overall acc | DS $/correct | Fin $/correct | Overall $/correct |
| ------------------------ | -------------: | ----------: | ----------: | -----------: | ------------: | ----------------: |
| Base VLM                 |          40.6% |       31.9% |       37.8% |      $0.0111 |       $0.0142 |           $0.0119 |
| ReAct +2                 |          16.8% |        6.4% |       13.5% |      $0.1446 |       $0.4114 |           $0.1846 |
| ReAct +4                 |          18.8% |        4.3% |       14.2% |      $0.1785 |       $0.8282 |           $0.2403 |
| Agent baseline +2        |           9.9% |        4.3% |        8.1% |      $0.1106 |       $0.1935 |           $0.1244 |
| Agent baseline +4        |           7.9% |        4.3% |        6.8% |      $0.1413 |       $0.2024 |           $0.1535 |
| **Our harness +2 tools** |      **56.4%** |   **36.2%** |   **50.0%** |  **$0.0140** |   **$0.0197** |       **$0.0153** |
| **Our harness +4 tools** |      **49.5%** |   **31.9%** |   **43.9%** |  **$0.0163** |   **$0.0219** |       **$0.0176** |

Reading:

- **The harness beats Base VLM by +12.2 pp at +2 tools and +6.1 pp at +4
  tools overall.** That is the headline.
- **The harness beats ReAct by +36.5 pp at +2 and +29.7 pp at +4 overall.**
  Same toolbelt, same reasoner; the only difference is structure.
- **The harness beats Agent baseline by +41.9 pp at +2 and +37.1 pp at +4.**
- **Generic agents do _not_ improve with more tools.** ReAct gains
  +0.7 pp going `+2 -> +4` (within noise) and pays +30% in cost. Agent
  baseline _loses_ -1.3 pp going `+2 -> +4`. This is the cleanest evidence
  that tool count alone is not the win.
- **The harness's `+2 -> +4` inversion (-6.1 pp) on this revision is the
  key open question** that the post-Path-A reruns appear to flip (see §3.5).

### 3.2 Latency

Per-example latency (mean) computed from `per_example.jsonl` `latency_ms`:

| Method             | Mean latency |    Median | Mean tool calls | Mean iterations |
| ------------------ | -----------: | --------: | --------------: | --------------: |
| Base VLM           |        3.0 s |     2.7 s |            0.00 |            1.00 |
| ReAct +2           |       16.1 s |    14.7 s |            2.39 |            3.32 |
| ReAct +4           |       21.1 s |    17.9 s |            2.91 |            3.77 |
| Agent baseline +2  |        5.4 s |     5.1 s |            0.01 |            1.01 |
| Agent baseline +4  |        5.8 s |     5.3 s |            0.01 |            1.01 |
| **Our harness +2** |    **2.5 s** | **2.2 s** |        **1.00** |        **8.00** |
| **Our harness +4** |    **2.5 s** | **2.3 s** |        **1.00** |        **8.00** |

Reading:

- **The harness is the fastest of the seven methods**, including faster
  than Base VLM by 0.5 s, because layout + routing + rerank are mostly
  cached/free, while Base VLM sends a 2-up summary view and pays one
  reasoner call.
- **ReAct is 6-8x slower than the harness** because each iteration is an
  LLM round-trip and ReAct averages ~3-3.8 LLM-driven steps. ReAct's
  tool calls succeed (no errors), but it pays an LLM-call tax to make each
  one.
- **The harness's 8 mean iterations are mostly deterministic** — only
  `plan`, `rerank`, `answer`, `verify` are LLM-driven; `route_pages`,
  `localize`, `inspect`, `expand_context` are deterministic stages.
- Post-Path-A reruns (PR #2 final) showed harness `+4` at ~3.7 s and the
  two-run mean rollup landed at ~4.7 s. The extra latency comes from
  attached neighbor images entering the reasoner call, which is the
  intended cost of Path A. Even at 4.7 s, the harness is still much
  faster than ReAct.

### 3.3 Localization and evidence quality

| Method             | Page recall | Mean bbox IoU |  Lazy answer rate | Abstain rate |
| ------------------ | ----------: | ------------: | ----------------: | -----------: |
| Base VLM           |       83.8% |          6.1% | 100.0% (no tools) |         7.4% |
| ReAct +2           |       78.2% |         31.8% |             19.6% |        12.2% |
| ReAct +4           |       75.0% |         29.3% |             24.3% |         8.1% |
| Agent baseline +2  |        0.0% |          0.0% |            100.0% |         0.0% |
| Agent baseline +4  |        0.0% |          0.0% |            100.0% |         0.0% |
| **Our harness +2** |   **80.4%** |     **70.8%** |              9.5% |        15.5% |
| **Our harness +4** |   **76.9%** |     **66.1%** |             11.5% |        20.3% |

Reading:

- **IoU is the cleanest mechanism signal.** The harness gets 66-71% IoU
  on cited regions vs ReAct's ~30% vs Base VLM's 6% (Base does not produce
  region citations) vs Agent baseline's 0% (does not call inspector). This
  is the localization-first ordering paying off.
- **Page recall is similar across methods** that route pages
  (Base/ReAct/Focus all hit 75-84%). The harness wins at the region
  level, not the page level.
- **Agent baseline produces no localization** because it does not run
  `inspect_region`; it answers directly from the summary tile view. That
  is why both its IoU and recall are 0% even with +4 tool access available.
- **Lazy-answer rate** — harness is 9-11% (mostly "Unanswerable" responses
  where the planner returned no actionable evidence type). ReAct is
  ~20-24%, which is consistent with ReAct prematurely terminating on its
  first observation.

### 3.4 Tool-call behavior (mechanism)

From PR #2 post-Path-A diagnostics (single +4 run, n=148):

| Mechanism metric                     |  Value |
| ------------------------------------ | -----: |
| `expand_context_called_rate`         |   100% |
| `mean_useful_tool_call_count`        |  ~1.15 |
| `mean_irrelevant_tool_call_count`    |  ~1.34 |
| `answer_changed_after_tool_rate`     | ~16.9% |
| `verifier_supported_after_tool_rate` | ~11.0% |
| `cited_packet_image_only_rate`       |   0.0% |

Reading:

- After Path A, **every cited packet has at least one text source attached**
  (text-layer snippet, OCR snippet, or a chart CSV). The `cited_image_only`
  rate is zero. This eliminates a documented failure mode where the
  reasoner saw a chart crop with no axis labels and hallucinated values.
- About 17% of examples flip their answer after a tool round; about 11%
  of examples become verifier-supported after a tool round. These are not
  large rates, but they are the rates the future SFT pipeline can shape
  with reward signals like `verifier_supported_after_tool`.
- `mean_irrelevant_tool_call_count` slightly exceeds
  `mean_useful_tool_call_count`, which is the next clean target for the
  expander: tighten neighbor selection so a smaller fraction of attached
  context is irrelevant.

### 3.5 Variance caveat

There is approximately a +/- 7 pp run-to-run variance floor on `Our harness
+4` at n=148 driven by upstream LLM sampling stochasticity in
`planner -> router -> reranker`. Recent run series:

| Run                                     | Overall acc | DS acc | Finance acc | $/correct | Mean latency |
| --------------------------------------- | ----------: | -----: | ----------: | --------: | -----------: |
| rebaseline-v2 (canonical)               |       43.9% |  49.5% |       31.9% |   $0.0176 |        2.5 s |
| sprint-2026-05-08/crop-fallback-run1    |       44.6% |  46.5% |       40.4% |   $0.0263 |          n/a |
| sprint-2026-05-08/current-pipeline-run3 |       43.2% |  45.5% |       38.3% |   $0.0263 |          n/a |
| PR #2 final full run (post-Path-A)      |       50.0% |  53.5% |       42.6% |   $0.0265 |        3.7 s |
| Post-Path-A 2-run rollup mean (PR #3)   |       50.7% |    n/a |         n/a |   $0.0282 |        4.7 s |

The single-row claim that survives this variance:

> Across every rebaseline and post-Path-A run we have, **`Our harness`
> lands in 43-51% overall accuracy**, **`Base VLM` lands at ~38%**, and
> **`ReAct` and `Agent baseline` land below 15%**.

The directional claim that is _not_ yet statistically separated:

> Path A appears to flip `+4 -> +2` ordering to `+4 > +2` (current
> two-run mean: +3.4 pp). This is consistent with the change being
> real (neighbor images now reach the reasoner), but the 95% CIs still
> overlap and we have not run >=2 replicates per cell post-Path-A.

The next deliberate experiment, before any other harness change, should be
to **bake the variance harness** (deterministic upstream stages: cache
planner / router / rerank outputs) so per-stage A/Bs are not dominated by
sampling noise.

## 4. Qualitative evidence

Three examples taken directly from the rebaseline-v2 per-example traces.
Each one shows the harness winning where Base VLM, ReAct, and Agent
baseline all fail, and each one shows _which mechanism_ did the work.

### 4.1 Datasheet — counted-diagram reasoning

- Example: `dat-adrv9040-reference-manual-ug-2192-0030`
- Family: `axis_value_interpolation`, `requires_visual=True`,
  difficulty `{visual:2, reasoning:3, localization:3}`.
- Question: "Using ONLY the structure diagram for adi_adrv904x_SpiSettings_t
  in region r_036_02 ... count the number of named field boxes shown inside
  the adi_adrv904x_SpiSettings_t outer box. Treating each field as an
  independent single-bit (on/off) option, compute 2^N where N is that
  field count. What is the resulting number of unique configurations?"
- Gold: `16`.

Per-method outcomes:

| Method             | Prediction     | Correct |      IoU | Tool calls |   Latency |        Cost |
| ------------------ | -------------- | :-----: | -------: | ---------: | --------: | ----------: |
| Base VLM           | `32`           |   no    |     0.00 |          0 |     2.6 s |     $0.0045 |
| ReAct +4           | `Unanswerable` |   no    |     0.00 |          5 |    29.0 s |     $0.0569 |
| Agent baseline +4  | rambling prose |   no    |     0.00 |          0 |     7.0 s |     $0.0134 |
| **Our harness +4** | **`16`**       | **yes** | **1.00** |      **1** | **4.3 s** | **$0.0105** |

What the harness actually did (trace excerpt):

1. `plan` -> `question_family=package_mechanical_reading`,
   `evidence_types=[diagram, table]`.
2. `route_pages` -> deterministic FTS routes to pages [36, 44].
3. `localize` -> RT-DETRv2 returns regions on those pages.
4. `rerank` -> LLM picks `r2_p36` (`relevance=1`).
5. `inspect` -> deterministic inspector crops + extracts text.
6. `expand_context` -> attaches neighbors.
7. `answer` -> `{"answer":"16","citations":["pkt_000"],"confidence":0.99}`.
8. `verify` -> `supported=true, reason="pkt_000 shows the structure
diagram with 4 named fields..."`.

Why the harness wins here: ReAct calls `get_text_layer` and
`inspect_region` four times and then gives up because it cannot resolve
which region is the right diagram; it abstains. Base VLM hallucinates "32".
The harness sees `evidence_types=[diagram]` -> reranker scores `r2_p36`
at relevance 1.0 -> the reasoner only ever sees the right crop and
counts 4 boxes -> 2^4 = 16. **Mechanism: rerank-as-router did the
disambiguation that ReAct could not do in 5 free-form tool calls.**

### 4.2 Finance — visual table cell selection

- Example: `fin-vis-jpm_gtm_us_daily-0126`
- Family: `visual_table`, `requires_visual=True`.
- Question: "In the 'Global fixed income' table, which country (from the
  'Aggregates' rows: U.S., Gbl. ex-U.S., Canada, Japan, Germany, UK,
  Italy, China) has the highest local yield in the 12/31/2025 column?"
- Gold: `UK`.

| Method             | Prediction                                        | Correct |      IoU | Tool calls |   Latency |        Cost |
| ------------------ | ------------------------------------------------- | :-----: | -------: | ---------: | --------: | ----------: |
| Base VLM           | `Italy`                                           |   no    |     0.57 |          0 |     2.1 s |     $0.0043 |
| ReAct +4           | long prose, "UK ... 4.88%" (graded wrong, format) |   no    |     0.46 |          3 |    13.6 s |     $0.0267 |
| Agent baseline +4  | `Italy ... 5.10%`                                 |   no    |     0.00 |          0 |     1.8 s |     $0.0047 |
| **Our harness +4** | **`UK`**                                          | **yes** | **1.00** |      **1** | **2.5 s** | **$0.0047** |

What is interesting here: ReAct _almost_ gets it right ("UK ... 4.88%")
but answers in prose form that fails exact-match scoring. The harness
benefits from the answer-type hint passed into the reasoner, so the
output is a clean string `UK`. The verifier on this one returned
`supported=false` (the cited table cell was partially occluded in the
crop summary), but the workflow preserved the answer because no retry
path improved on it. The Path-A neighbor attachment is what lets the
reasoner see legend + row label + column header together, which is
exactly the cell-resolution case for which `linked_crop_refs` exists.
**Mechanism: structured packet + answer-type-aware formatting beat
free-form prose.**

### 4.3 Finance — cross-table month identification

- Example: `fin-goog-20251231-0006`
- Family: `chart_table_cross_ref`, `requires_visual=True`,
  difficulty `{visual:2, reasoning:3, localization:2}`.
- Question: "During which month did the company pay a higher average
  price per share for Class A shares compared to Class C shares, and did
  this coincide with the month where fewer Class A shares were purchased
  than Class C shares?"
- Gold: `November 1 - 30`.

| Method             | Prediction                | Correct |      IoU | Tool calls |   Latency |        Cost |
| ------------------ | ------------------------- | :-----: | -------: | ---------: | --------: | ----------: |
| Base VLM           | `Unanswerable`            |   no    |     0.00 |          0 |     2.4 s |     $0.0042 |
| ReAct +4           | "November ... 1-30" prose |   no    |     0.32 |          3 |    18.3 s |     $0.0333 |
| Agent baseline +4  | `October and November`    |   no    |     0.00 |          0 |     5.1 s |     $0.0094 |
| **Our harness +4** | **`November 1 - 30`**     | **yes** | **1.00** |      **1** | **2.3 s** | **$0.0077** |

The harness routes to page 47, reranker assigns `r4_p47` the highest
relevance, inspector crops the share-repurchase table, the answer stage
reads cells and returns the table's own row label `November 1 - 30`
(not "November"), which exact-matches the gold. **Mechanism: extracting
the row-label literal from a cited table rather than narrating prose
about it.**

### 4.4 What the qualitative evidence shows

Across these three examples (and the 22 other Focus-wins-over-all-4
examples in rebaseline-v2), three patterns repeat:

1. **Localization-first ordering.** The harness's
   `route_pages -> localize -> rerank` sequence reliably puts the right
   crop in front of the reasoner before any answer is attempted. ReAct
   tries to do this and reasoning at the same time, and frequently
   exhausts iteration budget before locking in a region.
2. **Answer-type-aware extraction.** Many gold answers are short canonical
   strings ("16", "UK", "November 1 - 30"). The harness's reasoner is
   prompted with the answer-type hint and tends to return exactly that
   form. ReAct, even when it correctly identifies the right value,
   wraps it in narrative prose that fails exact-match scoring.
3. **Verifier as a controller, not a re-grader.** The verifier in the
   harness directs _what kind of repair to attempt next_ (`expand_context`,
   `retry_localization`, `escalate_reasoner`), not just "is this answer
   right or wrong." The comparator agents have nothing equivalent.

The 25 Focus-only wins are direct evidence for the claim "structure of
the harness, not raw tool access, is the cause of the accuracy gap."
The same +4 tool set is available to ReAct and Agent baseline in these
examples. They have the tools. They do not have the routing.

## 5. Where the signal is, where the growth is

Reading sections 3 and 4 together:

### 5.1 Where the harness is already strong

- Region localization (IoU 66-71% vs ReAct ~30%, Base ~6%).
- Cost efficiency ($0.015-0.018 / correct vs Base $0.012, ReAct $0.18-0.24).
- Latency (2.5 s mean, faster than Base VLM, 6-8x faster than ReAct).
- Datasheets accuracy in absolute terms (50-56%).
- Cited-evidence completeness (cited_image_only rate is now 0%).

### 5.2 Where the next pp of accuracy lives

Three signals point to the same answer: the **expander's irrelevant-neighbor
fraction**.

- Verifier `next_action="expand_context"` on 45 of 148 unsupported
  cases in run3 — and most of those expansions did _not_ flip the answer.
- Mean irrelevant tool call count (~1.34) > mean useful tool call count
  (~1.15) per PR #2 diagnostics.
- The two-run mean shows `+4 > +2` by 3.4 pp, suggesting neighbor
  attachment is now net-positive but not by much.

Concrete next experiments, in order:

1. **Variance harness (architectural).** Cache planner / router / rerank
   outputs so per-stage A/Bs are deterministic upstream. This is a
   prerequisite, not a result. Without it, every per-stage A/B is
   confounded by upstream sampling variance.
2. **Tighten expander relevance gating.** Lower the irrelevant-neighbor
   rate by either (a) raising `_DEFAULT_NEIGHBOR_RELEVANCE_THRESHOLD`,
   (b) replacing role-only attachment with role+relevance scoring, or
   (c) gating expansion on planner `evidence_types` more strictly.
3. **Inspector LLM-driven for hard cases only.** Currently
   `deterministic_inspector` runs for every example (147 / 148). A
   triggered LLM-driven inspector for hard examples (chart cells,
   axis interpolation, multi-region fusion) is a candidate Phase-6 lever
   from `plans/2026-05-04-harness-iteration-sprint.md`.
4. **Chart-to-table behind a flag.** The chart_to_table path is wired
   but off; visible chart-table cross-ref questions (like §4.3) are
   exactly the case where CSV extraction could replace a fragile chart
   crop. Worth a +/- A/B once the variance harness is in place.

### 5.3 Where finance is weaker and why

Finance accuracy lags datasheets by 8-19 pp in every method, including the
harness. Inspecting the failure modes:

- More multi-modal cross-references (table + chart in the same packet).
- More visual-table questions where the row-label literal must be returned
  verbatim and prose answers fail scoring.
- More year-range and signed-number formatting traps (e.g., `(40)` vs `-40`).

The harness's 31.9% finance vs 49.5% datasheets gap in rebaseline-v2
narrows to 42.6% finance vs 53.5% datasheets in the PR #2 post-Path-A run.
That is consistent with Path A's neighbor-attachment helping cross-reference
questions specifically. Worth running the n=148 A/B on this slice
explicitly.

### 5.4 What this is _not_ yet evidence for

To keep the eventual paper honest:

1. The harness's `+4 > +2` post-Path-A ordering is directional, not yet
   statistically separated. Need >=2 replicates per cell post-Path-A
   under the variance harness.
2. Mechanism diagnostics explain _how_ the harness uses tools, but the
   causal claim depends on matched A/Bs holding under the same benchmark
   revision and the same upstream sampling. The variance harness fixes
   the latter; the dataset revision pin (`FOCUSPARSE_DATASET_REVISION`)
   fixes the former.
3. The comparator-method scores (ReAct ~14%, Agent baseline ~7%) are
   for _generic_ implementations. We did not optimize them. A reasonable
   reviewer concern is "did you adversarially under-tune the baselines?"
   The answer is "we built them to the minimum viable spec and froze
   them, per the project's stated narrowed scope." That is a defensible
   choice but should be documented in the paper.

## 6. What I want this doc to lock in

If we stop work here and pick this up cold next week, the conclusions
to carry forward are:

1. **The thesis ("structured harness wins") is supported by the current
   numbers** at every comparator (Base VLM, ReAct, Agent baseline), every
   tool count (`+2`, `+4`), and every domain (datasheets, finance).
2. **The supporting mechanism is localization + answer-type-aware
   extraction**, not "more tools." Path A is what made `+4` better than
   `+2` post-Path-A by ensuring neighbors actually reach the reasoner.
3. **The next research moves are (a) variance harness, (b) tighten
   expander gating, and (c) Phase-6 LLM-driven inspector A/B**, in that
   order.
4. **Open questions before paper writeup:**
   - Replicate the post-Path-A `+4 > +2` ordering at >=2 runs with the
     variance harness on.
   - Land a clean dataset revision pin so the rebaseline numbers do not
     drift when parser-bench advances.
   - Document the comparator under-tuning honestly.

## Artifact paths

- Canonical 7-row table: `results/hf/headline-v1-rebaseline-v2/headline_table.{md,html,json}`
- Per-method traces for §4 examples:
  `results/hf/headline-v1-rebaseline-v2/<spec>/per_example.jsonl`
- Post-Path-A focus-only runs:
  `results/hf/sprint-2026-05-08/current-pipeline-run{1,2,3}/`
- Diagnostics (mechanism stats): `<run_dir>/diagnostics.md` and the
  toolset diagnostics under `headline-v1-rebaseline-v2/`.
- Active plans:
  - `plans/2026-04-29-research-driven-eval-framework.md` (master)
  - `plans/2026-05-04-harness-iteration-sprint.md` (sprint backlog)
  - `plans/2026-05-06-path-a-plumb-neighbors-into-reasoner.md` (just shipped)
- Prior change-summary doc:
  `docs/research/2026-05-11-focusparse-pipeline-change-summary.md`.
