# FocusParse Pipeline Change Summary

Date: 2026-05-11  
Scope: merged work from PR #1, PR #2, and PR #3 after the Path A / inspect-expand iteration.

This document explains the substantive FocusParse pipeline changes made during the
recent research sprint. It is meant to be a handoff-quality record: what changed,
why it matters for the research claim, where the code lives, what the current eval
signal says, and what caveats remain.

## Research Context

The sprint was organized around one claim:

> A structured, query-conditioned, budget-aware agentic harness improves parsing on
> high-resolution domain-specific documents because it localizes, constructs, and
> verifies evidence more effectively than base VLMs, generic ReAct loops, or generic
> agent baselines.

The implementation focus was deliberately narrow:

- Improve the middle of the pipeline: `localize -> inspect -> expand_context -> answer -> verify`.
- Make the evidence pathway stronger before chasing more benchmark breadth.
- Keep the headline table reproducible across:
  - Base VLM
  - ReAct +2 tools
  - ReAct +4 tools
  - Agent baseline +2 tools
  - Agent baseline +4 tools
  - Our harness +2 tools
  - Our harness +4 tools
- Track accuracy, cost, latency, tool behavior, verifier behavior, trace path, and failure reasons.

## PR And Commit Map

| PR | Merge commit | Purpose |
| --- | --- | --- |
| [#1](https://github.com/gabrielkmbo/FocusParse/pull/1) | `56185e1` | Improve inspect/expand evidence repair and verifier-directed retries. |
| [#2](https://github.com/gabrielkmbo/FocusParse/pull/2) | `4627df8` | Instrument toolset behavior and surface latency in metrics/tables. |
| [#3](https://github.com/gabrielkmbo/FocusParse/pull/3) | `225210b` | Export machine-readable headline table artifacts and enrich older rollups with latency. |

The most important pipeline files touched were:

- `src/focusparse/pipeline/workflow.py`
- `src/focusparse/pipeline/inspector.py`
- `src/focusparse/pipeline/expander.py`
- `src/focusparse/pipeline/reasoner.py`
- `src/focusparse/pipeline/verifier.py`
- `src/focusparse/evidence/packet.py`
- `src/focusparse/eval/harness.py`
- `scripts/diagnose_predictions.py`
- `scripts/run_hf_eval.py`
- `scripts/run_headline_eval.py`
- `scripts/render_headline_table.py`
- `scripts/enrich_headline_table_latency.py`

## Pipeline Behavior Before This Sprint

The harness already had the right high-level shape:

```text
plan -> route_pages -> localize -> inspect -> expand_context -> answer -> verify
```

The failure mode was in the evidence pathway. The pipeline could often find a
plausible region, but the reasoner would see a packet that was too raw or too
isolated:

- A chart crop without its axis labels, legend, or caption.
- A table cell without row/column headers or footnotes.
- A picture-like evidence packet where the verifier could not see supporting text.
- Neighbor crops produced by `expand_context` but not actually reaching the reasoner.
- Retry logic that did not reliably target the packet or missing context the verifier named.

The sprint therefore focused on making evidence packets answerable, not just
making region localization look good.

## Evidence Packet Contract Changes

File: `src/focusparse/evidence/packet.py`

`EvidencePacket` remains the load-bearing contract: the reasoner receives packets,
not raw pages.

Important packet fields now used by the pipeline:

- `multi_scale_crops`
  - Ordered crop variants for the same target region.
  - Supported scales now include:
    - `tight`
    - `context`
    - `chart_context`
    - `zoomed`
- `linked_crop_refs`
  - Neighbor image crops attached by `expand_context`.
  - Examples: caption, footnote, legend, section header, context window.
- `linked_neighbor_types`
  - Role labels for the linked crops so the reasoner knows why an image follows.
- `text_layer_snippet`
  - Native PDF text extracted from the packet bbox when available.
- `ocr_snippet`
  - OCR fallback or advisory OCR for visual regions.
- `chart_csv` and `chart_extraction_confidence`
  - Optional chart-to-table extraction, gated behind the chart feature flag.

Why this matters:

The reasoner now receives a structured evidence packet with both primary evidence
and role-labeled context. This directly supports the research claim that disciplined
evidence construction matters more than simply giving an agent more tools.

## Inspector Changes

File: `src/focusparse/pipeline/inspector.py`

The inspector was upgraded from "pack raw regions" toward "construct answerable
evidence packets."

Substantial changes:

1. Page-image fallback cropping

   When a source PDF is unavailable, the inspector can crop from staged page
   images. This matters for HF eval paths where a PDF may not be supplied or
   where text routing falls back to the rendered pages.

2. Native text first, OCR fallback second

   For text-bearing regions, the inspector prefers deterministic PDF text via
   `get_text_layer`. If that is unavailable or too sparse, it falls back to OCR
   on the crop.

3. Advisory OCR for visual packets

   Visual regions still commit as image evidence, but OCR can expose axis labels,
   tick labels, captions, or callouts to later verifier summaries.

4. Chart and visual context crops

   Some visual questions need slightly wider context even when the tight crop is
   correct. The inspector now selectively adds context crops for question families
   such as:

   - `curve_axis_reading`
   - `legend_series_binding`
   - `multi_chart_comparison`
   - `timing_diagram_reading`

   The crop scale is recorded as `context` or `chart_context`, so the reasoner can
   distinguish it from the primary target crop.

5. Optional auto-zoom

   Tiny or fine-detail crops can be upsampled through the sandboxed `run_python`
   tool when `auto_zoom` is enabled. The zoomed crop is additive, not destructive:
   it becomes another `CropRef(scale="zoomed")`.

6. Optional chart-to-table extraction

   Chart extraction remains gated and off by default for headline runs. When
   enabled, chart regions can include a CSV representation alongside the crop.

Important design choice:

The inspector does not globally add more images. It gates context by question
family, region type, relevance, and packet position. This was necessary because
early broader context expansion created noise and could hurt accuracy.

## Expand Context Changes

File: `src/focusparse/pipeline/expander.py`

`expand_context` is now an evidence repair stage rather than a passthrough.

It attaches nearby, role-labeled context regions to existing packets:

- captions
- footnotes
- legends
- axis labels
- titles
- section headers
- page headers/footers
- row/column headers
- wider context windows around cited packets

Key mechanics:

1. Query-conditioned neighbor selection

   The expander uses planner `evidence_types`, reranker roles, verifier
   diagnostics, and spatial adjacency. It does not blindly attach every nearby
   region.

2. Bounded neighbor budget

   Defaults keep neighbor count small:

   - default max neighbors per packet: 2
   - fallback max when no plan/reranker signal exists: 1
   - initial total neighbor cap for reranked expansion: 6

   This was a direct response to observed context overload.

3. Verifier-directed retry expansion

   When the verifier says `next_action=expand_context`, the workflow passes:

   - verifier reason
   - missing context hints
   - target packet ids
   - cited packet ids

   Expansion then targets the relevant packet instead of widening every packet.

4. Missing-context vocabulary

   The verifier can request missing context such as:

   - caption
   - legend
   - footnote
   - header
   - continuation
   - axis_label
   - row_header
   - column_header
   - unit
   - x_axis
   - y_axis

5. Readability and visual retry repairs

   Some verifier failures are not "missing caption" failures; they are "the crop
   is too small or unreadable" failures. The expander can now create wider or
   zoomed context windows around the cited packet for those cases.

6. Text-only context

   Header-like neighbors with extracted text can be sent as text-only context
   rather than extra images. This preserves useful context without spending image
   budget on redundant crops.

Why this matters:

This is the core harness-vs-tools distinction. The improvement is not "more tools
are always better." The improvement is that the harness controls when and how
tools create answerable evidence.

## Reasoner Changes

File: `src/focusparse/pipeline/reasoner.py`

The reasoner prompt and image collection now understand the richer packet layout.

Substantial changes:

1. Linked neighbor images reach the reasoner

   Path A fixed a dead-code issue: `expand_context` populated
   `linked_crop_refs`, but the reasoner image collector did not include them.
   The reasoner now sees:

   ```text
   tight crop -> context/chart_context/zoomed crops -> linked neighbor crops
   ```

2. Neighbor roles are named in packet descriptors

   Packet lines now say when attached neighbor images exist and list their roles.
   Example roles:

   - caption
   - footnote
   - legend
   - section_header
   - context_window

3. Text-only context is explicit

   Header-like extracted context can appear as text in the packet descriptor
   instead of as an image.

4. System prompt explains primary vs context evidence

   The reasoner is told:

   - `tight` is the target region.
   - `context` and `chart_context` are wider crops for labels, axes, legends,
     and surrounding geometry.
   - `zoomed` is a readable upsampled copy of the same tight crop.
   - attached neighbor images are context, not separate answer candidates.
   - `context_window` is a wider crop around the cited packet.

5. Exact-answer formatting was tightened

   The reasoner receives answer-type hints so exact-match and numeric answers
   are less likely to include prose that fails scoring.

Why this matters:

The reasoner can now interpret the evidence packet structure instead of treating
all images as equivalent candidates. This is essential when a chart crop and a
caption crop appear together.

## Verifier Changes

File: `src/focusparse/pipeline/verifier.py`

The verifier now acts as a controller, not only a judge.

It returns a structured `next_action`:

- `accept`
- `retry_localization`
- `expand_context`
- `abstain`
- `escalate_reasoner`

Substantial changes:

1. Constraint-aware verification

   The verifier prompt explicitly checks units, conditions, labels, qualifiers,
   entity names, domain tags, and min/max/superlative constraints.

2. Missing-context diagnostics

   For `expand_context`, the verifier can emit `diagnostics.missing_context`.
   The workflow forwards this into `expand_context`.

3. Target packet ids

   For readability or context-window repair, the verifier can name target packet
   ids. The retry then focuses on those packets.

4. Richer packet summaries

   Verifier summaries include more packet text and focus on cited packet content.
   This helps distinguish "the evidence is missing" from "the answer misread
   evidence that is already present."

5. Better action selection

   The verifier is instructed to prefer `escalate_reasoner` when evidence is
   sufficient but the answer extracted or computed the wrong value, and to use
   `expand_context` only when a missing neighbor or readability repair is needed.

Why this matters:

The verifier's failure mode classification now drives pipeline control flow. This
is the basis for measuring evidence localization success, supportedness, and retry
effectiveness.

## Workflow Changes

File: `src/focusparse/pipeline/workflow.py`

The workflow now has a more explicit controlled retry loop.

Substantial changes:

1. Split retry budgets

   There is a general `max_retries` and a separate `max_evidence_retries`.
   Evidence repairs can be enabled without turning every verifier action into a
   broad retry.

2. Tool-set axis is real

   `tool_set="minimal"` means:

   - `inspect_region`
   - `get_text_layer`

   `tool_set="full"` adds:

   - `expand_context`
   - `run_python`

   In minimal mode, `expand_context` is skipped as a passthrough and `auto_zoom`
   is forced off. This makes +2 vs +4 a real ablation.

3. Retry mutation depends on verifier action

   - `retry_localization` lowers the localizer threshold and reruns
     localize/rerank/inspect/expand.
   - `expand_context` widens adjacency, forwards verifier diagnostics, and
     focuses retry evidence on target/cited packets.
   - `escalate_reasoner` keeps evidence fixed but passes the verifier reason as
     an escalation hint to the reasoner.

4. Best unsupported answer selection

   If retry exhaustion produces a worse abstention or weaker answer, the workflow
   can retain the better unsupported answer and records the selection in trace
   debug events.

5. Telemetry additions

   The workflow now records:

   - `retries_used`
   - `evidence_retries_used`
   - `loop_terminated`
   - `loop_retry_helped`
   - `available_tools`
   - `answer_changed_after_tool`
   - `verifier_supported_after_tool`

Why this matters:

The harness can now explain its own behavior: which tools were available, which
tools were selected, whether a tool retry changed the answer, and whether the
verifier supported the post-tool answer.

## Toolset Instrumentation

Files:

- `src/focusparse/eval/harness.py`
- `scripts/diagnose_predictions.py`
- `src/focusparse/pipeline/workflow.py`

The pipeline now emits the fields needed to study +2 vs +4 tool behavior:

- `available_tools`
- `selected_tools`
- `tool_call_sequence`
- `useful_tool_call_count`
- `irrelevant_tool_call_count`
- `failed_tool_call_count`
- `answer_changed_after_tool`
- `verifier_supported_after_tool`

The diagnostics script summarizes:

- tool sequence top-k
- available tool belts
- selected tool belts
- verifier unsupported rate
- verifier next-action distribution
- expand-context called rate
- mean neighbors attached
- mean neighbors added
- failure reason distribution
- cited packet text coverage
- cited packet linked-context rate
- cited packet image-only rate

Current PR #2 final run diagnostics showed:

- selected tools: `inspect_region + expand_context`
- available tools: `inspect_region + get_text_layer + expand_context + run_python`
- `expand_context_called_rate`: 100%
- `mean_useful_tool_call_count`: about 1.15
- `mean_irrelevant_tool_call_count`: about 1.34
- `answer_changed_after_tool_rate`: about 16.9%
- `verifier_supported_after_tool_rate`: about 11.0%
- `cited_packet_image_only_rate`: 0%

Caveat:

These diagnostics are mechanism evidence, not a causal proof by themselves. They
show how the harness uses tools and where retries help, but the causal claim still
depends on matched +2/+4 and baseline comparisons.

## Eval And Artifact Changes

Files:

- `src/focusparse/eval/metrics.py`
- `src/focusparse/eval/schemas.py`
- `scripts/run_hf_eval.py`
- `scripts/run_headline_eval.py`
- `scripts/render_headline_table.py`
- `scripts/enrich_headline_table_latency.py`

Substantial changes:

1. Latency is now a first-class aggregate metric

   `AggregateMetrics` and `PerProtocolResults` include `latency_ms_mean`.
   HF eval wrappers and headline table builders carry this field forward.

2. Headline renderer includes latency columns

   Markdown and HTML headline tables now include:

   - datasheet latency
   - finance latency
   - overall latency

3. Machine-readable table exports

   `scripts/render_headline_table.py` now emits:

   - `.md`
   - `.html`
   - `.csv`
   - `.jsonl`

   The CSV/JSONL exports flatten method x domain cells into rows with:

   - method
   - agent
   - tool_set
   - domain
   - n
   - accuracy and CI bounds
   - cost per correct and CI bounds
   - latency in ms and seconds
   - bbox IoU
   - page recall
   - total cost

4. Post-hoc latency enrichment for older rollups

   `scripts/enrich_headline_table_latency.py` reads old headline tables and
   cached run artifacts, then fills missing `latency_ms_mean` from `run.json` or
   `per_example.jsonl`.

   This avoids rerunning expensive model evals just to add latency to historical
   comparison tables.

## Current Headline Results

Seven-row latency-enriched rollup:

- `results/hf/sprint-2026-05-08/final-main-rollup/headline_table_with_current_focus_means_latency.json`
- `results/hf/sprint-2026-05-08/final-main-rollup/headline_table_with_current_focus_means_latency.md`
- `results/hf/sprint-2026-05-08/final-main-rollup/headline_table_with_current_focus_means_latency.html`
- `results/hf/sprint-2026-05-08/final-main-rollup/headline_table_with_current_focus_means_latency.csv`
- `results/hf/sprint-2026-05-08/final-main-rollup/headline_table_with_current_focus_means_latency.jsonl`

Overall headline table:

| Method | Overall accuracy | Overall cost/correct | Overall latency |
| --- | ---: | ---: | ---: |
| Base VLM | 37.8% | $0.0119 | 3.01s |
| ReAct +2 tools | 13.5% | $0.1846 | 16.15s |
| ReAct +4 tools | 14.2% | $0.2403 | 21.11s |
| Agent baseline +2 tools | 8.1% | $0.1244 | 5.42s |
| Agent baseline +4 tools | 6.8% | $0.1535 | 5.82s |
| Our harness +2 tools | 47.3% | $0.0290 | 4.79s |
| Our harness +4 tools | 50.7% | $0.0282 | 4.68s |

Final PR #2 single full +4 run:

| Metric | Value |
| --- | ---: |
| n | 148 |
| Overall accuracy | 50.0% |
| Datasheet accuracy | 53.5% |
| Finance accuracy | 42.6% |
| Total cost | $1.96 |
| Cost per correct | $0.0265 |
| Mean latency | 3.69s |

Artifact path:

- `results/hf/sprint-2026-05-09/pr2-final-full-run1/`

## Research Interpretation

The current signal supports these careful claims:

1. The structured FocusParse harness beats generic ReAct and generic agent
   baselines by a wide margin on the current n=148 split.

2. The harness beats Base VLM overall in the current rollup, especially on
   datasheets.

3. Finance remains weaker and more variable than datasheets.

4. More tools are not automatically better in generic agents. The generic +4
   rows are slower and less accurate than the harness, which supports the idea
   that disciplined tool routing matters.

5. Within the harness, +4 is directionally better than +2 in the current
   two-run mean:

   ```text
   Our harness +2: 47.3% overall
   Our harness +4: 50.7% overall
   delta: +3.4pp
   ```

6. The +4 vs +2 difference should still be treated cautiously because confidence
   intervals overlap and model-run variance is material.

## Verification Performed

The sprint included focused test and lint checkpoints. Important final checks:

- PR #2 checkpoint:
  - `172 passed`
  - ruff check clean
  - ruff format check clean
- PR #3 checkpoint:
  - `61 passed`
  - ruff check clean
  - ruff format check clean

Representative test files added or expanded:

- `tests/test_inspector.py`
- `tests/test_expander.py`
- `tests/test_reasoner.py`
- `tests/test_verifier.py`
- `tests/test_workflow.py`
- `tests/test_focus_harness.py`
- `tests/test_diagnose_predictions.py`
- `tests/test_metrics.py`
- `tests/test_hf_eval_cli.py`
- `tests/test_render_headline_table.py`
- `tests/test_enrich_headline_table_latency.py`

## Known Caveats

1. The diagnostics are not yet a causal ablation.

   They explain tool behavior, but causal claims still need matched A/B
   comparisons under the same benchmark revision and model conditions.

2. The finance domain is still the weaker domain.

   The harness is competitive, but finance chart-reading remains more fragile
   than datasheet extraction.

3. Confidence intervals overlap in several comparisons.

   Current results are strong directionally, but the project should avoid
   overstating statistically separated gains where the CI gate says "hold."

4. Optional features remain off by default.

   These include:

   - `auto_zoom`
   - `multi_scale_packets`
   - `chart_to_table`
   - `use_react_inspector`
   - `use_evidence_graph`

   They are implemented or partially wired but should be flipped only after
   clean n=148 A/B evidence.

5. Results artifacts are gitignored.

   The code that generates and renders them is committed, but local result
   files under `results/` are not source-controlled.

## Practical Next Steps

1. Use the latency-enriched seven-row table as the main current result table.

2. Run any new pipeline experiment as a matched n=148 A/B with at least two
   replicates when touching +4, because prior focus +4 variance was roughly
   several percentage points.

3. Prioritize finance failures where:

   - localization is correct,
   - verifier marks unsupported,
   - missing context is axis/legend/visual readability,
   - `answer_changed_after_tool` is false.

4. Treat +4 tool access as a routing problem, not a tool-count problem.

   The useful next claim is not "more tools are good" or "more tools are bad."
   The sharper claim is:

   > Tool access helps when the harness constrains selection, evidence packet
   > construction, and verifier-directed repair.

