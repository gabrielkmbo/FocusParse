# FocusParse: Evidence Packets for High-Resolution Document QA

Submission-facing draft: 2026-05-24

Status: conservative paper draft. This file is intended to be the clean
submission source that can later be converted to LaTeX or a workshop template.
It uses only claims that are either raw-artifact verified in the current
checkout or explicitly labeled as provisional. Supporting audits live beside it
in `docs/research/paper-draft/`.

## Abstract

High-resolution technical and financial PDFs expose a persistent failure mode
for multimodal document question answering: whole pages preserve context but
compress away small labels, footnotes, and chart/table details, while tight
crops recover readability but detach evidence from the local context needed to
interpret it. We study this failure mode using parser-bench, a
citation-required visual QA benchmark over finance reports and technical
datasheets where answers are evaluated with both correctness and page/box
grounding. We introduce FocusParse, a structured harness that routes to likely
pages, localizes candidate regions, inspects high-resolution crops, expands
selected evidence with role-labeled neighboring context, and answers only from
compact evidence packets. In a matched seven-method run on the pinned 148-row
paper slice, FocusParse +4 reaches 61.5% overall accuracy, 66.3% datasheet
accuracy, and 51.1% finance accuracy, compared with 43.9% for a base VLM and
6.1%-18.2% for generic tool-agent comparators. The same run shows high page
recall (0.914), strong region overlap (0.857 mean BBox IoU), and low lazy
answering (3.4%). The resulting thesis is that performance on dense finance
and datasheet documents depends not merely on bigger context windows or more
tools, but on constructing the right evidence unit before reasoning: a readable
region plus the captions, legends, headers, footnotes, axes, and cross-page
references that make the region meaningful.

## 1. Introduction

Document AI systems increasingly need to answer questions over high-resolution
PDFs rather than simply transcribe them. In finance reports and technical
datasheets, the answer often depends on small plotted labels, multi-panel
figures, footnotes, min/typ/max tables, timing diagrams, and symbol dictionaries
spread across multiple pages. This creates a resolution-context tradeoff. A
full-page VLM call can preserve surrounding layout but may make fine details
unreadable. A tight crop can make the relevant text or visual element readable
but may lose the caption, legend, table header, or footnote that determines what
the crop means.

FocusParse is built around the claim that the useful intermediate object for
this setting is an evidence packet. An evidence packet binds a localized region
to its supporting context: local crop, text/OCR snippets, role-labeled neighbor
crops, provenance, confidence, and optional extracted structure. The method is
deliberately narrower than a general-purpose parser. It is a harness for
query-conditioned evidence construction in dense documents where the answer
must be tied to supporting pages and boxes.

This draft makes four contributions:

1. It frames parser-bench as a region-grounded QA setting for concentrated
   finance and datasheet documents.
2. It describes FocusParse, an evidence-localization-first harness with
   explicit inspect and expand stages.
3. It defines an experiment plan comparing base VLMs, generic ReAct loops,
   generic tool agents, and FocusParse under matched tools and scorers.
4. It analyzes current artifacts using answer accuracy, cost per correct,
   page recall, BBox IoU, lazy-answer rate, and qualitative packet traces.

## 2. Related Work

Document parsing benchmarks such as DocLayNet, PubTabNet, GTE/FinTabNet,
OmniDocBench, MPDocBench-Parse, and external RunLlama ParseBench show that
document pages contain structured visual regions and that parsing quality
should be evaluated beyond plain OCR [@doclaynet2022; @pubtabnet2020;
@gtefintabnet2021; @omnidocbench2025; @mpdocbenchparse2026; @parsebench2026].
MPDocBench-Parse is useful because it moves parsing evaluation toward practical
multi-page documents, semantic continuity, hierarchy, and visual-content
preservation. External ParseBench is especially relevant because it evaluates
agent-facing parsing along tables, charts, content faithfulness, semantic
formatting, and visual grounding. FocusParse asks a different but adjacent
question: not whether a page or multi-page document can be fully parsed, but
whether a QA system can select the answer-supporting evidence for a query,
attach the local context needed to interpret it, and cite the supporting
page/box. Throughout this draft, `ParseBench` refers to the RunLlama parsing
benchmark, while `parser-bench` refers to the Gabriel benchmark used for
FocusParse evaluation.

Document QA and financial QA benchmarks establish the need for multimodal and
domain-specific reasoning. DocVQA, InfographicVQA, and MMLongBench-Doc study
questions over document images and long multimodal contexts [@docvqa2021;
@infographicvqa2021; @mmlongbenchdoc2024]. FinQA, TAT-QA, FinanceBench, and
FinRAGBench-V emphasize numerical reasoning, open-book financial QA, and visual
citations [@finqa2021; @tatqa2021; @financebench2023; @finragbenchv2025].
Parser-bench differs by making high-resolution region localization, multi-piece
context collection, and page/crop citation part of the QA contract.

Chart and table QA benchmarks such as ChartQA and PlotQA show that charts
require both visual perception and reasoning [@chartqa2022; @plotqa2020].
FocusParse places this challenge inside long PDFs where chart interpretation
often depends on neighboring captions, axes, legends, footnotes, or table
references. The chart-reading problem is therefore inseparable from evidence
collection: the model must read the mark and recover the nearby semantics that
make the mark meaningful.

The closest methodological neighbors are AgenticOCR and DocLens. AgenticOCR
argues that page-level chunking introduces extraneous context and dilutes
salient evidence, reframing OCR as query-conditioned on-demand extraction
[@agenticocr2026]. DocLens identifies evidence localization as a central
failure mode in long visual document understanding and navigates from documents
to pages and elements before answer adjudication [@doclens2025]. FocusParse
shares the active evidence-acquisition motivation, but studies a controlled
stage machine with explicit typed evidence packets and role-labeled context
expansion. The contrast is the object handed to the reasoner: a compact packet
containing a readable crop plus captions, legends, headers, footnotes, axes, or
neighboring regions, rather than a loose transcript of tool observations.

Generic ReAct-style agents provide a natural baseline for tool use
[@react2023]. The key comparison is not tools versus no tools. It is
unconstrained tool use versus structured evidence construction. Generic loops
may inspect documents, but in dense PDFs they can also terminate lazily, repeat
irrelevant calls, or answer from noisy transcripts that contain weak citations.

## 3. Parser-Bench Dataset

Parser-bench is a citation-required visual QA benchmark over full-resolution
finance reports and technical datasheets. Each example contains a question, a
gold answer, answer-type metadata, source document metadata, rendered page
images, supporting pages, supporting bounding boxes, optional alternate boxes,
question-family labels, difficulty axes, and reasoning-chain metadata.

The current paper slice is the canonical post-filter validation materialization
used by the FocusParse research artifacts:

| Slice | Rows | Unique IDs | Source PDFs | Datasheet | Finance |
| --- | ---: | ---: | ---: | ---: | ---: |
| Canonical paper slice | 148 | 147 | 44 | 101 | 47 |

Evidence complexity:

| Measure | Rows |
| --- | ---: |
| Multi-region examples | 70 |
| Multi-page examples | 34 |
| Requires visual evidence | 112 |
| Requires visual evidence and multi-region | 49 |
| Evidence page spread >= 50 | 6 |

Answer types:

| Answer type | Rows |
| --- | ---: |
| `exact_match` | 93 |
| `numeric` | 48 |
| `boolean` | 5 |
| `unanswerable` | 2 |

The most frequent question families are `axis_value_interpolation`,
`near_miss_distractor`, `cross_page_continuation`,
`min_typ_max_disambiguation`, and `chart_table_cross_ref`. These families are
exactly where inspection and context expansion matter: visual labels must be
read at high resolution, then connected to the surrounding document semantics.

Dataset provenance is tracked in
`docs/research/paper-draft/dataset-characterization.md` and
`docs/research/paper-draft/pinned-dataset-provenance.md`. The current pinned
materialization uses HF revision
`3774c67f8b814392b6d04c939e904f749a3f52eb`, dataset fingerprint
`835d8b90da8f7c1a`, and benchmark JSONL SHA-256
`e85b4df5032bc9e49fc74e1ed7492001794fbf4b46cc0f35d31a4cf32277962b`.
The final submission must carry this pin into the full result manifest or
explicitly regenerate the counts if the pin changes.

## 4. FocusParse Method

FocusParse is an eight-stage workflow:

```text
PLAN -> ROUTE_PAGES -> LOCALIZE -> RERANK -> INSPECT -> EXPAND_CONTEXT -> ANSWER -> VERIFY
```

The stages communicate through typed events rather than arbitrary scratchpad
state. Planning predicts question family and evidence types. Routing chooses
candidate pages. Localization and reranking propose visual/textual regions.
Inspection turns selected regions into readable evidence by cropping,
extracting text/OCR, and optionally using region-specific tools. Expansion
attaches bounded context such as captions, legends, headers, axes, footnotes,
and nearby table text. Answering receives evidence packets rather than raw
pages. Verification checks whether the answer is supported, whether citations
are grounded, and whether a bounded repair action is needed.

The central contract is `EvidencePacket`. A packet contains:

- `packet_id`, page, normalized box, region type, and provenance;
- local crop references and optional multi-scale crop references;
- text-layer and OCR snippets;
- linked neighbor crop references and neighbor-role labels;
- optional chart/table extraction;
- confidence and selection metadata.

This design creates an explicit bottleneck: the reasoner can only use compact
evidence assembled by the upstream stages. That bottleneck is the mechanism the
paper tests.

## 5. Experiments

The intended main comparison has seven rows:

| Method | Tool access | Purpose |
| --- | --- | --- |
| Base VLM | none | Tests single-shot VLM reasoning without evidence construction. |
| ReAct +2 | `inspect_region`, `get_text_layer` | Tests a generic tool loop with core tools. |
| ReAct +4 | + `expand_context`, `run_python` | Tests whether generic loops benefit from more tools. |
| Agent baseline +2 | same +2 tools | Tests a thinner generic agent baseline. |
| Agent baseline +4 | same +4 tools | Tests tool count without FocusParse structure. |
| FocusParse +2 | minimal harness tools | Tests structured evidence construction without full context expansion. |
| FocusParse +4 | full harness tools | Tests the complete inspect/expand harness. |

Metrics:

- answer accuracy with 95% bootstrap confidence intervals;
- cost per correct answer;
- mean latency;
- page recall;
- mean BBox IoU;
- lazy-answer rate;
- mean tool calls;
- qualitative packet traces.

The main raw-artifact verified matched table is:

```text
results/hf/paper/2026-05-24-paper-headline-v1/headline/headline_table.json
```

The older 66.9% `shape-normalizer-full-run1` checkpoint is documented but not
locally recoverable in this checkout, so it remains provisional and should not
be used as the submission headline unless recovered or rerun.

## 6. Results

### 6.1 Main Matched Table

Source:

```text
results/hf/paper/2026-05-24-paper-headline-v1/headline/headline_table.json
```

| Method | Overall | Datasheet | Finance | $/correct | Page recall | BBox IoU | Lazy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Base VLM | 43.9% | 47.5% | 36.2% | $0.0102 | 0.848 | 0.000 | 100.0% no-tool |
| ReAct +2 | 18.2% | 22.8% | 8.5% | $0.1341 | 0.819 | 0.336 | 16.2% |
| ReAct +4 | 16.2% | 20.8% | 6.4% | $0.1946 | 0.727 | 0.309 | 24.3% |
| Agent baseline +2 | 8.1% | 10.9% | 2.1% | $0.1324 | 0.000 | 0.000 | 100.0% |
| Agent baseline +4 | 6.1% | 7.9% | 2.1% | $0.1811 | 0.000 | 0.000 | 100.0% |
| FocusParse +2 | 60.1% | 64.4% | 51.1% | $0.0282 | 0.929 | 0.897 | 2.7% |
| FocusParse +4 | 61.5% | 66.3% | 51.1% | $0.0248 | 0.914 | 0.857 | 3.4% |

FocusParse +4 improves over the base VLM by 17.6 overall points, 18.8
datasheet points, and 14.9 finance points. It improves over generic ReAct and
generic agent baselines by 43-55 overall points while remaining much cheaper
per correct than those tool-agent comparators. Base VLM remains cheapest per
correct, so the claim is an accuracy and localization gain, not a lowest-cost
claim.

Diagnostics show that FocusParse +4 builds 1184 evidence packets, calls
`expand_context` on every example, attaches 9.72 neighbors on average, and
cites packets with 100% text coverage and 84.4% linked-context coverage.
Generic ReAct calls tools but does not construct evidence packets, while the
generic agent baselines mostly terminate without useful tool use.

### 6.2 Mechanism Ablations

The mechanism ablations separate first-pass evidence construction from
post-answer repair:

| Condition pair | Baseline | Full +4 | Delta | Recoveries | Regressions | Mechanism read |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| No rerank -> rerank | 56.1% | 61.5% | +5.4 pp | 19 | 11 | Query-conditioned ordering materially improves both accuracy and grounding. |
| No `expand_context` -> expand | 59.5% | 61.5% | +2.0 pp | 14 | 11 | Role-labeled context expansion helps, especially on datasheets, but is not uniformly beneficial. |
| Repair off -> repair on | 62.8% | 61.5% | -1.4 pp | 9 | 11 | The current repair loop is a mixed control, not the source of the main gain. |
| Answer-shape repair off -> on | 64.2% | 61.5% | -2.7 pp | 9 | 13 | Answer-shape repair is a negative control; scorer-shape normalization is not carrying the gain. |

The strongest causal evidence is therefore reranking and evidence packet
construction, not verifier repair. The repair-off row preserves verifier
scoring but prevents verifier feedback from triggering a second pass; telemetry
shows zero answer/evidence retries on all 148 rows. The answer-shape row
preserves full evidence construction and non-shape repair, but disables
answer-shape-specific retry hints and accepted-retry selection guards; it is a
useful over-correction diagnostic rather than a positive mechanism.

### 6.3 Failure Taxonomy

The final FocusParse +4 row is correct on 91/148 examples and incorrect on
57/148 examples. The generated failure taxonomy uses the same primary
classifier as `scripts/diagnose_predictions.py`:

| Failure bucket | Count | Datasheet | Finance | Error share | All-row share |
| --- | ---: | ---: | ---: | ---: | ---: |
| Verifier unsupported | 26 | 16 | 10 | 45.6% | 17.6% |
| Partial localization | 12 | 6 | 6 | 21.1% | 8.1% |
| Localization miss | 8 | 5 | 3 | 14.0% | 5.4% |
| Reasoning/extraction | 7 | 4 | 3 | 12.3% | 4.7% |
| Lazy/no bbox | 4 | 3 | 1 | 7.0% | 2.7% |

The dominant remaining error is not generic tool laziness: only 4/57 errors
are lazy/no-bbox failures. The largest bucket is verifier-unsupported answers
after evidence collection, followed by incomplete or missed localization. This
supports the analysis claim that the next lift is likely better
verification/evidence adjudication and multi-region localization, not simply
adding more tools. The generated artifacts are under
`results/paper/failure-taxonomy/`.

### 6.4 Provisional Stronger Checkpoint

Research notes record `shape-normalizer-full-run1` at 99/148, or 66.9%, with
page recall 0.949, BBox IoU 0.881, and lazy rate 0.020. This is the likely
stronger headline if recovered or reproduced, but the raw run directory is not
present. The paper should not use it as the final abstract result until the raw
artifact package exists.

## 7. Qualitative Figures

Figure 1, pipeline schematic:

```text
plan -> route -> localize -> rerank -> inspect -> expand -> answer -> verify
```

Purpose: show how FocusParse differs from a generic ReAct transcript by forcing
intermediate artifacts through typed stages.

Figure 2, evidence packet diagram:

Purpose: show a local crop plus role-labeled neighbors such as caption, legend,
axis label, header, footnote, and cross-page reference.

Figure 3, Latvia finance cross-region example:

Example id: `fin-bis_qr_2025_mar-0050`. The answer is `Latvia`. The figure
should show the two chart-panel regions plus the country-abbreviation table on
page 8. In the final FocusParse +4 run, this row has page recall `1.0`, BBox
IoU `0.9999935073355983`, and the tool sequence `inspect_region`,
`expand_context`, `expand_context`. This remains the strongest main-text
finance qualitative figure. The current draft panel is
`results/paper/qualitative-figure-panels/figure3-finance-latvia-evidence-binding.png`.

Figure 4, JESD204B cross-page datasheet example:

Example id: `dat-JESD204B-Survival-Guide-0029`. The answer is `6`. This should
show the timing diagram count on page 16 and the corroborating lane/path block
diagram evidence across pages 16 and 73. In the final FocusParse +4 run, this
row has page recall `1.0`, BBox IoU `0.9999916798927161`, and the tool sequence
`inspect_region`, `expand_context`, making it the clean primary datasheet
success figure. The current draft panel is
`results/paper/qualitative-figure-panels/figure4-datasheet-jesd204b-evidence-binding.png`.

Figure 5, Infineon Q1/Q2 near-miss example:

Example id:
`dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0052`.
The answer is `Q1 (HS)`. This is best used as an analysis or appendix example
because the answer is correct but BBox IoU is only 0.256.

Figure 6, ADRV9040 compaction near-miss:

Example id: `dat-adrv9040-reference-manual-ug-2192-0032`. The gold answer is
`ADRV9040_FW.bin, 641 kb`, but the final-run prediction is
`ADRV9040_FW.bin`. The scorer marks the row correct, yet the answer omits the
requested size field. Use this as an answer-shape or field-preservation
analysis case, not as a main success figure.

Figure provenance is tracked in
`docs/research/paper-draft/qualitative-figure-manifest.md`. Same-revision
baseline predictions for the two main qualitative examples are tracked in
`docs/research/paper-draft/qualitative-baseline-comparisons.md`.

## 8. Limitations

The current dataset slice is small and concentrated: 148 rows with 47 finance
examples. The paper therefore reports confidence intervals and should avoid
broad claims about all document QA. The strongest 66.9% result is documented
but not yet raw-artifact verified in this checkout. The current qualitative
panels and failure taxonomy are draft analysis artifacts; final styling still
depends on the selected venue template and page budget. Zotero export is
blocked until the local Zotero Desktop app and API are available on this
profile. Finally, FocusParse is a research harness, not a general document
parser or production service.

## 9. Conclusion

FocusParse studies a concrete mechanism for high-resolution document QA:
construct the evidence before asking the model to answer. On the pinned
148-row parser-bench paper slice, FocusParse +4 reaches 61.5% accuracy with
strong page and region grounding, outperforming both a no-tool base VLM and
generic tool-agent comparators. The more important mechanism signal is that
structured inspect and expand stages produce compact packets that preserve both
readability and interpretive context. This supports the paper's central claim:
for dense finance and datasheet documents, better harnesses are not just models
with larger context windows or more tools. They are systems that build the
right evidence object before reasoning.

## Submission Gates

Before submission:

1. Commit or externally archive the exact code/docs used to build the final
   table; a slim review archive exists at
   `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32.tar.gz`,
   with a sibling `.tar.gz.sha256` checksum sidecar.
2. Keep the abstract on the verified 61.5% matched result unless the 66.9%
   checkpoint is recovered/rerun.
3. Use `venue-template-conversion-audit.md` to convert the draft panels and
   failure-taxonomy table into the selected venue template once the target
   workshop/conference is known.
4. Port `neurips-checklist-prep.md` into the selected venue checklist with
   stable section references and target-policy-compliant artifact/LLM-use
   disclosures.
5. Use `source-pdf-and-asset-license-audit.md` to select a public/anonymized
   artifact release mode before distributing source-derived page/crop assets;
   the current source-safer package is
   `results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10.tar.gz`,
   with a sibling `.tar.gz.sha256` checksum sidecar.
6. Install/start Zotero Desktop and export/check the bibliography.
7. Replace moving GitHub and Hugging Face URLs with pinned revisions or archive
   DOIs where possible.
