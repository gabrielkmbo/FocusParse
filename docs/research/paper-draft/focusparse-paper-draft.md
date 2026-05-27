# FocusParse: Evidence-Packet Construction for High-Resolution Document QA

Draft date: 2026-05-24

Status: working research-paper draft. This is submission-shaped prose, not yet
camera-ready. The current submission-safe headline is the matched seven-method
run at `results/hf/paper/2026-05-24-paper-headline-v1/`; the older 66.9%
candidate remains historical/provisional until its raw artifacts are recovered
or rerun.

Submission-facing companion:
`docs/research/paper-draft/focusparse-submission-draft.md`.

## Abstract

High-resolution finance reports and technical datasheets often answer questions
through small visual details: a tick label inside a chart, a table cell whose
meaning depends on a header, a caption that disambiguates a diagram, or a
footnote that changes a numeric interpretation. Single-shot vision-language
models retain broad page context but compress away these small details. Local
crops recover readability but frequently detach the evidence from the surrounding
text, legend, caption, axis, or cross-page context needed for a correct answer.
We present FocusParse, a structured, budget-aware document QA harness that
constructs compact typed evidence packets before final reasoning. FocusParse
plans the evidence need, routes to candidate pages, localizes regions, inspects
high-resolution crops, expands them with role-labeled neighboring context, and
verifies answer support. We evaluate on a canonical 148-example slice of
parser-bench, a citation-required high-resolution QA benchmark over finance and
datasheet PDFs. In a matched seven-method run on the pinned 148-row paper
slice, FocusParse +4 reaches 61.5% overall accuracy, 66.3% datasheet accuracy,
and 51.1% finance accuracy, compared with 43.9% for a base VLM and
6.1%-18.2% for generic tool-agent comparators. The central finding is that tool
availability is not enough: strong performance on dense documents depends on
controlled evidence localization, context expansion, compaction, and
verification before reasoning.

## 1. Introduction

Document parsing is becoming infrastructure for agents. Financial analysts,
credit systems, procurement tools, hardware engineers, and operational agents all
consume PDFs whose critical facts are not available as clean text. In these
settings, document QA is not only a language task. The system must decide where
to look, inspect the relevant visual detail at sufficient resolution, recover
nearby context, and cite the supporting evidence.

Dense finance and datasheet PDFs make this especially difficult. The answer may
be a country label inside one panel of a financial chart, a threshold in a
datasheet curve, a min/typ/max value whose interpretation depends on a condition
row, or a package dimension whose label is visible only in a tightly cropped
diagram. A full-page VLM call keeps layout context but may compress away the
tiny mark that matters. A crop-only system can make the mark readable while
losing the caption, legend, row header, footnote, or neighboring panel that
gives the mark meaning.

Recent document systems increasingly recognize evidence localization as the
central bottleneck. AgenticOCR frames visual document parsing as query-driven
on-demand extraction rather than page-level chunking [@agenticocr2026].
DocLens uses tool-augmented agents to navigate from long documents to relevant
pages and elements before answer adjudication [@doclens2025]. New benchmarks
such as ParseBench and OmniDocBench also emphasize semantic correctness,
grounding, and fine-grained document structure rather than shallow text overlap
[@parsebench2026; @omnidocbench2025]. These works motivate the same broad
direction: models need more than raw OCR. They need the right evidence.

FocusParse studies a narrower and more testable claim: for high-resolution
finance and datasheet QA, the load-bearing intervention is not a generic tool
loop. It is disciplined evidence construction. FocusParse uses a fixed stage
machine:

```text
plan -> route_pages -> localize -> rerank -> inspect -> expand_context -> answer -> verify
```

The reasoner never sees raw pages directly. Instead, it sees a list of typed
`EvidencePacket` objects, each containing a target crop, optional multi-scale
crops, text/OCR snippets, role-labeled linked neighbors, provenance, and
confidence. The packet is the central abstraction: it lets the system preserve
readable local evidence and the surrounding context needed to interpret it.

This draft makes four contributions:

1. We define parser-bench as a region-grounded QA setting over concentrated
   high-resolution finance and datasheet PDFs, where answers are evaluated for
   both correctness and evidence localization.
2. We introduce FocusParse, a structured harness for evidence localization,
   inspection, expansion, compaction, and verification.
3. We compare FocusParse with a base VLM, generic ReAct loops, and generic agent
   baselines under matched tools, reasoner, protocol, and scorer.
4. We analyze mechanisms through answer accuracy, cost, latency, page recall,
   BBox IoU, lazy-answer rate, and qualitative traces.

## 2. Related Work

### Document Parsing Benchmarks

Document parsing benchmarks have moved from narrow layout or table subtasks
toward end-to-end semantic correctness. DocLayNet provides a large
human-annotated layout-analysis dataset with diverse page layouts and labeled
bounding boxes [@doclaynet2022]. PubTabNet focuses on image-based table
recognition and HTML reconstruction, exposing the difficulty of converting table
images into machine-readable structure [@pubtabnet2020]. GTE/FinTabNet extends
this line into complex scientific and financial tables with detailed table
structure annotations [@gtefintabnet2021]. OmniDocBench expands the evaluation
surface to diverse PDF document parsing with layout categories and attributes
[@omnidocbench2025]. MPDocBench-Parse further moves parsing evaluation toward
practical multi-page documents, including semantic continuity, hierarchy
recovery, reading order, table merging, and visual-content preservation
[@mpdocbenchparse2026]. External ParseBench argues that agent-facing parsing
should be judged by semantic correctness across tables, charts, content
faithfulness, formatting, and visual grounding; its public README reports
2,078 unique enterprise pages and a five-dimension leaderboard headed by
LlamaParse Agentic at 84.88 overall [@parsebench2026].

These benchmarks are critical context, but FocusParse targets a different
failure point. Rather than asking whether a page or multi-page document can be
fully parsed, parser-bench asks whether a system can answer a query from the
right localized evidence, attach the context needed to interpret that evidence,
and cite the supporting page/box. This makes evidence construction directly
measurable. In this draft, `ParseBench` refers to the RunLlama parsing
benchmark, while `parser-bench` refers to Gabriel's citation-required QA
dataset.

### Document, Long-Document, And Financial QA

DocVQA helped establish document visual question answering as a task where
models must answer user questions over document images rather than only
transcribe them [@docvqa2021]. InfographicVQA pushed this further into documents
whose answers require joint reasoning over layout, text, graphical elements, and
data visualizations [@infographicvqa2021]. MMLongBench-Doc then stresses
long-context multimodal document understanding, including questions whose
evidence may appear across different sources, pages, and visual components
[@mmlongbenchdoc2024].

Financial QA benchmarks emphasize a complementary axis: domain-specific
reasoning over financial reports. FinQA and TAT-QA focus on numerical reasoning
over financial text, tables, or hybrid table-text contexts [@finqa2021;
@tatqa2021]. FinanceBench evaluates open-book financial QA over public-company
filings and highlights that naive retrieval or long-context prompting remains
unreliable in enterprise-style settings [@financebench2023]. FinRAGBench-V is
especially close in motivation because it evaluates multimodal financial RAG
with visual citations [@finragbenchv2025].

FocusParse is narrower than these benchmarks but more diagnostic for the
mechanism studied here. It uses finance and datasheet PDFs where the answer must
be tied to supporting pages and regions. The key question is not only whether a
model can reason over finance, tables, or long documents. It is whether the
system can assemble the exact visual and textual evidence needed before the
reasoner answers, especially when that evidence spans a crop plus a caption,
legend, footnote, header, or neighboring panel.

### Chart And Table Question Answering

ChartQA introduced chart question answering with visual and logical reasoning,
including human-written questions and generated chart-summary questions
[@chartqa2022]. PlotQA highlighted that realistic plot questions often require
real-valued answers outside a fixed vocabulary and cannot be solved by
extracting a visible text token alone [@plotqa2020]. These datasets show that
charts require both visual perception and reasoning.

FocusParse inherits that challenge but places it back inside long, dense PDFs.
The chart is rarely isolated. It may be surrounded by captions, legends, table
references, footnotes, symbol dictionaries, or multiple neighboring panels. The
central failure is not only reading a chart; it is assembling the chart and its
linked context.

### Query-Conditioned And Agentic Document Systems

AgenticOCR reframes OCR as query-conditioned, on-demand parsing. It argues that
page-level chunking injects excess context and dilutes salient evidence, while
visual-token compression increases hallucination risk [@agenticocr2026].
DocLens similarly treats long visual document understanding as an evidence
localization problem, navigating to relevant pages and elements before
sampling/adjudicating an answer [@doclens2025]. These papers are the closest
methodological neighbors: both move away from passive full-page ingestion and
toward active evidence acquisition.

FocusParse is closest to these systems. Its contrast is architectural and
evaluative. First, FocusParse uses a controlled stage machine rather than an
open-ended agent loop. Second, it explicitly represents evidence as typed
packets with linked neighbor roles, so the reasoner sees "this crop plus its
caption/legend/axis/header" rather than a flat list of images. Third,
parser-bench evaluates answer correctness together with page and region
localization, allowing mechanism claims about evidence quality rather than only
final-answer accuracy.

This is also the distinction emphasized by the research-refresh slide deck:
the missing capability is not only to zoom into evidence, but to assemble
multi-piece context before reasoning. The inspect stage makes the evidence
readable; the expand stage makes it interpretable.

### Generic Tool-Using Agents

ReAct introduced an influential pattern for interleaving reasoning traces and
actions so language models can gather information from external environments
while solving a task [@react2023]. Generic ReAct-style document agents inherit
that flexibility, but flexibility is also a failure mode. They interleave
localization, inspection, and reasoning in one loop. In dense PDFs, tool calls
can accumulate without sharpening the evidence: the agent may inspect the wrong
page, repeatedly query text that lacks visual labels, terminate lazily, or
answer from a transcript that contains many unrelated observations. FocusParse
separates these responsibilities into stages. The comparison is therefore not
"tools versus no tools"; it is "unconstrained tool use versus structured
evidence construction."

### Failure-Mode Summary

The related-work matrix tracked in
`docs/research/paper-draft/related-work-failure-matrix.md` turns the literature
review into a failure analysis:

| Related family | What it establishes | Remaining gap |
| --- | --- | --- |
| Parsing/layout benchmarks | Pages contain structured visual regions and parsing needs grounding. | A parsed page is not the same as query-conditioned evidence selection. |
| Long-document and financial QA | Documents require multimodal and numerical reasoning over realistic sources. | Long context and retrieval do not guarantee readable, cited visual evidence. |
| Chart/table QA | Charts and tables require visual structure and numeric reading. | Standalone charts/tables omit the surrounding PDF context that often decides the answer. |
| Query-conditioned document systems | Whole-page parsing is wasteful when the question needs only specific evidence. | Localization still needs typed compaction and role-labeled neighbor attachment. |
| Generic tool agents | Reasoning/action loops can use OCR, crops, and retrieval tools. | Flexible tool use can be lazy, noisy, expensive, and weakly grounded. |

FocusParse is positioned at this remaining gap: it asks whether a controlled
harness can localize, inspect, expand, compact, and verify evidence before final
answer generation. Live-source verification for this related-work framing is
tracked in `docs/research/paper-draft/external-source-audit.md`.

## 3. Parser-Bench Dataset

Parser-bench is a citation-required visual QA benchmark over high-resolution
financial documents and technical datasheets. Each example contains:

- a natural-language question;
- a gold answer;
- an answer type, optional unit, and tolerance;
- source PDF metadata and rendered page images;
- supporting pages;
- supporting bounding boxes;
- optional alternate boxes and evidence relations;
- domain, difficulty, question family, and stress metadata.

At the schema level, this means a benchmark row is not only a QA item. It is an
answer-plus-evidence object: `BenchmarkExample` records the answer type,
optional unit and tolerance, source PDF, rendered page images, gold supporting
pages, gold supporting boxes, alternate boxes, evidence relations,
multi-region/visual flags, difficulty axes, question family, stress type, and a
reasoning chain. The evidence fields are what make parser-bench suitable for
testing evidence construction rather than only final-answer generation.

The FocusParse paper slice is the canonical post-filter validation set used in
the current research artifacts:

| Split | Rows | Unique IDs | Source PDFs | Datasheet | Finance | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Canonical paper slice | 148 | 147 | 44 | 101 | 47 | Stress variants filtered before evaluation |

The slice is deliberately concentrated. It contains 70 multi-region examples,
34 multi-page examples, 112 rows that require visual evidence, and 49 rows that
are both visual and multi-region. Answer types are mostly `exact_match` (93)
and `numeric` (48), with smaller `boolean` (5) and `unanswerable` (2) groups.
The most frequent question families are `axis_value_interpolation` (26),
`near_miss_distractor` (20), `cross_page_continuation` (19),
`min_typ_max_disambiguation` (16), and `chart_table_cross_ref` (13). The
full characterization lives in
`docs/research/paper-draft/dataset-characterization.md`.

The stress-filter distinction matters. The public Hugging Face dataset surface
contains more rows and stress variants. FocusParse evaluation uses
`materialize_split()` followed by `_filter_stress_rows()`, keeping rows whose
`stress_type` is empty or `none`. Prior provenance notes record this as 219
validation rows minus 71 stress rows, yielding 148 canonical examples. The paper
must report the exact HF revision and code commit used for materialization.

The public dataset is distributed as an embedded-image Hugging Face dataset.
FocusParse first materializes the selected split to a local staging directory,
writing a `benchmark.jsonl` plus page PNGs under a `data/processed/.../images/`
layout. This preserves compatibility with parser-bench's filesystem-oriented
runner while giving the paper a single materialization point to fingerprint.
At the time of this draft, the default local staging file only contains one row,
while the pinned paper materialization and five related-work staging directories
contain byte-identical 148-row materializations with SHA-256
`e85b4df5032bc9e49fc74e1ed7492001794fbf4b46cc0f35d31a4cf32277962b`.
The current paper pin is HF revision
`3774c67f8b814392b6d04c939e904f749a3f52eb` with dataset fingerprint
`835d8b90da8f7c1a`; the final paper should carry this pin into the submission
result directory or regenerate this table if the pin changes.

### Question Families

Parser-bench is designed to expose failure modes that are common in dense
technical and financial documents:

- axis value interpolation;
- legend-series binding;
- chart-caption and chart-footnote fusion;
- chart-table cross-reference;
- multi-chart comparison;
- min/typ/max disambiguation;
- condition-footnote fusion;
- cross-page continuation;
- package and timing-diagram reading;
- near-miss distractors and unanswerable cases.

This taxonomy is important because FocusParse's method is query-conditioned. The
planner predicts evidence types and question family, then later stages use that
prediction to bias region ranking, inspection mode, and context expansion.

### Evaluation

Parser-bench scores both answer correctness and evidence localization. Answer
types include numeric, exact-match, multiple-choice, boolean, and unanswerable
forms. Localization is evaluated with supporting pages and bounding boxes. This
lets the paper distinguish three cases that a plain answer metric would conflate:

1. The model answered correctly from the right evidence.
2. The model found the right evidence but extracted or formatted the answer
   incorrectly.
3. The model answered from the wrong evidence or no evidence.

That distinction is the basis for the paper's mechanism analysis.

## 4. FocusParse Method

FocusParse is a structured harness that constructs compact evidence before final
reasoning. It is implemented as an eight-stage workflow:

```text
PLAN -> ROUTE_PAGES -> LOCALIZE -> RERANK -> INSPECT -> EXPAND_CONTEXT -> ANSWER -> VERIFY
```

The implementation uses typed events between stages:
`QuestionEvent -> PlanEvent -> PagesEvent -> RegionsEvent -> EvidenceEvent ->
AnswerEvent -> VerdictEvent`. This is the key design separation from a generic
tool-using agent. A stage cannot silently pass arbitrary scratchpad state to the
reasoner; it must produce a typed artifact that can be inspected, scored, and
ablation-tested.

### 4.1 Planning

The planner classifies the question into a family, predicts evidence types, and
sets an approximate budget class. Examples of evidence types include chart,
table, diagram, text, caption, legend, footnote, axis label, and header. This
stage turns an open-ended document question into a concrete evidence request.
The planner uses parser-bench's domain-specific family vocabulary and emits a
strict JSON plan; malformed or missing fields fall back to conservative defaults
so planning errors do not crash the harness.

### 4.2 Page Routing

The router chooses candidate pages using text and available page signals. Page
routing is not the final evidence decision. It only bounds the search space for
region localization. This separation prevents page-level retrieval from being
treated as sufficient evidence.

In the current implementation, page routing is recall-biased. When page text is
available, a SQLite FTS index ranks pages by the question and returns a small
candidate set by default. When text is absent or the query has no matches, the
router falls back to the page universe rather than dropping evidence. The trace
records reason codes for these cases.

### 4.3 Region Localization And Reranking

The localizer proposes candidate regions on routed pages. A reranker then scores
regions against the question and tags their likely role, such as legend binding,
axis reading, caption context, footnote adjustment, table-cell lookup, or header
disambiguation. This is where FocusParse begins to differ from generic agents:
region relevance is decided before answer reasoning begins.

The localizer is layout-driven: it calls the layout detector on each routed page
and converts detected boxes to normalized `RegionCandidate` objects. Detector
confidence remains separate from page-router score, because page selection and
box relevance answer different questions. The reranker then adds
query-conditioned relevance, `needed_for` roles, and missing-context hints, so a
small legend or footnote can outrank a visually obvious but irrelevant region.

### 4.4 Inspection

The inspector converts region candidates into evidence packets. Its primary tool
is `inspect_region`, which has exactly three modes:

- `image`: render and crop the region;
- `element`: crop plus OCR;
- `region`: crop plus sub-layout detection and per-sub-region OCR.

The inspector prefers native PDF text when available, falls back to OCR when
needed, and runs advisory OCR on visual regions so chart labels or diagram
callouts are visible to later stages. For fine-detail regions it can add wider
context crops or upsampled crops through a sandboxed Python tool.

Inspection is therefore a readability operation, not only a crop operation. The
stage can carry a tight crop, a wider context crop, a chart-context crop, or a
zoomed crop for the same target region. For chart-bearing question families, the
inspector can also attach structured chart/table output, but failures leave the
visual packet intact.

### 4.5 Evidence Packet Contract

The reasoner sees `EvidencePacket` objects, not raw pages. Each packet can carry:

- a stable packet id for citation;
- page and normalized bounding box;
- target crop reference;
- page thumbnail reference;
- multi-scale crop references such as tight, context, chart-context, or zoomed;
- linked neighbor crop references;
- linked neighbor role labels;
- text-layer and OCR snippets;
- optional chart CSV;
- provenance and confidence.

This packet is the harness's central compaction mechanism. It preserves the
local evidence and the context that makes it meaningful while keeping irrelevant
page content out of the reasoner prompt.

### 4.6 Context Expansion

`expand_context` attaches nearby role-labeled context to inspected packets. It
considers captions, footnotes, legends, axis labels, section headers, page
headers/footers, titles, row/column headers, and wider context windows. Expansion
is bounded and query-conditioned. It uses planner evidence types, reranker roles,
spatial adjacency, and verifier diagnostics. This prevents the method from
degenerating into "send every nearby crop."

This stage directly targets the full-page-versus-crop tradeoff. The crop is
readable, while expansion restores the local document semantics needed to reason
from it.

### 4.7 Answering And Verification

The answerer receives the compact packet set and answer-type hints. It must
return an answer plus packet citations. The verifier then checks whether the
answer is supported by the cited packets. The verifier is also a controller: it
can accept, ask for localization retry, request context expansion, abstain, or
escalate the reasoner with a targeted hint.

The verifier loop is deliberately bounded. FocusParse is not an unbounded ReAct
loop. Most work happens inside typed stages that produce measurable artifacts.

### 4.8 Difference From Generic Tool Agents

The scientific comparison is not "tool use versus no tool use." ReAct-style
agents also call tools, but they interleave localization, inspection, and answer
generation inside one loop. FocusParse makes evidence construction explicit and
measurable: routing produces pages, localization produces boxes, inspection
produces crops and text, expansion produces role-labeled neighbors, and only
then does the reasoner answer. This is why the experiments report page recall,
BBox IoU, lazy-answer rate, and cost per correct rather than only final
accuracy.

## 5. Experiments

### 5.1 Compared Methods

The clean all-method comparison uses seven rows:

| Method | Tool access | Scientific purpose |
| --- | --- | --- |
| Base VLM | none | Tests single-shot VLM reasoning without harness evidence construction. |
| ReAct +2 | `inspect_region`, `get_text_layer` | Tests whether a generic loop with the core tools is enough. |
| ReAct +4 | + `expand_context`, `run_python` | Tests whether generic loops benefit from more tools. |
| Agent baseline +2 | same +2 belt | Tests a thinner generic agent baseline. |
| Agent baseline +4 | same +4 belt | Tests tool count without FocusParse structure. |
| FocusParse +2 | minimal harness tools | Tests the harness without context expansion / Python zoom. |
| FocusParse +4 | full harness tools | Tests the full evidence-construction harness. |

All rows use the same benchmark slice, protocol, answer scorer, and primary
reasoner family in the recorded artifacts. Cost is computed from the repo's
pricing table at run time; for a submission, pricing should be refreshed or
reported as a point-in-time experimental cost.

### 5.2 Metrics

We report:

- answer accuracy;
- 95% bootstrap confidence intervals where available;
- cost per correct answer;
- mean latency;
- page recall;
- mean BBox IoU;
- lazy-answer rate;
- mean tool calls;
- verifier supportedness and retry behavior for mechanism analysis.

### 5.3 Artifact Provenance Policy

The paper distinguishes three evidence tiers. A raw artifact-verified result has
the current `run.json`, `per_example.jsonl`, row count, code commit, and dataset
revision available for inspection. A documented result is recorded in research
memos or changelogs but is not yet locally reproducible from raw artifacts. A
diagnostic result is a slice, smoke test, posthoc rescore, or partial report.

This distinction matters because the strongest documented FocusParse result is
not the current submission-safe artifact. The current worktree now verifies the
matched seven-method run at
`results/hf/paper/2026-05-24-paper-headline-v1/`. The 66.9%
`shape-normalizer-full-run1` result is recorded in the research memo and
changelog, but its raw result directory is not present in this checkout. The
paper draft therefore treats 61.5% as the submission-safe headline and 66.9% as
a candidate until recovered or rerun.

## 6. Results

The working result audit is
`docs/research/paper-draft/experiments-results-audit.md`. The draft separates
raw-verified results from documented-but-missing artifacts so the paper does not
accidentally promote a research-note number into a submission claim.

### 6.1 Final Matched Seven-Method Table

The current submission-safe main result is:

```text
results/hf/paper/2026-05-24-paper-headline-v1/headline/headline_table.json
```

| Method | Overall | Datasheet | Finance | Cost/correct | Latency | Page recall | BBox IoU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Base VLM | 43.9% | 47.5% | 36.2% | $0.0102 | 2.52s | 0.848 | 0.000 |
| ReAct +2 | 18.2% | 22.8% | 8.5% | $0.1341 | 14.00s | 0.819 | 0.336 |
| ReAct +4 | 16.2% | 20.8% | 6.4% | $0.1946 | 14.40s | 0.727 | 0.309 |
| Agent baseline +2 | 8.1% | 10.9% | 2.1% | $0.1324 | 5.21s | 0.000 | 0.000 |
| Agent baseline +4 | 6.1% | 7.9% | 2.1% | $0.1811 | 5.25s | 0.000 | 0.000 |
| FocusParse +2 | 60.1% | 64.4% | 51.1% | $0.0282 | 3.30s | 0.929 | 0.897 |
| FocusParse +4 | 61.5% | 66.3% | 51.1% | $0.0248 | 3.20s | 0.914 | 0.857 |

This table is backed by seven `run.json` files and seven 148-row
`per_example.jsonl` files under the result root. It uses HF revision
`3774c67f8b814392b6d04c939e904f749a3f52eb`, the 148-row staged slice, and the
source-PDF cache at `/Users/gabrielbo/.cache/focusparse/pdfs`.

### 6.2 Candidate 65%+ Headline

The slide deck and `docs/research/2026-05-15-harness-65plus-post-evidence-iteration.md`
record a stronger candidate result:

| Run | Correct | Accuracy | Datasheet | Finance | Cost/correct | Latency | Page recall | BBox IoU | Lazy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `shape-normalizer-full-run1` | 99/148 | 66.9% | 71/101 | 28/47 | $0.0232 | 3.70s | 0.949 | 0.881 | 0.020 |

This should become the submission headline only after raw artifact provenance is
recovered or reproduced. The required proof package is:

- `run.json`;
- `per_example.jsonl`;
- code commit SHA;
- HF dataset revision;
- exact materialization and stress-filter logs;
- qualitative trace/crop evidence for selected examples.

Until then, the draft treats this as a candidate headline, not a final claim.

### 6.3 Mechanism: Localization Quality

The clearest mechanism signal is BBox IoU. In the final matched table,
FocusParse +4 reaches 0.857 mean BBox IoU and FocusParse +2 reaches 0.897,
while ReAct is about 0.31-0.34 and generic agent baselines produce no usable
region grounding. This supports the thesis that the harness wins by sharpening
evidence before answer generation.

Page recall is less separated. Base VLM, ReAct, and FocusParse often identify
the right page or page neighborhood. The difference is at the region and packet
level: FocusParse finds and packages the relevant crop and its context.

### 6.4 Mechanism Ablations

The paper now has four n=148 mechanism ablations against the same final
FocusParse +4 row:

| Condition pair | Baseline | Full +4 | Delta | Recoveries | Regressions | Mechanism read |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| No rerank -> rerank | 56.1% | 61.5% | +5.4 pp | 19 | 11 | Query-conditioned ordering improves both accuracy and grounding. |
| No `expand_context` -> expand | 59.5% | 61.5% | +2.0 pp | 14 | 11 | Context expansion gives a modest overall gain, concentrated in datasheets. |
| Repair off -> repair on | 62.8% | 61.5% | -1.4 pp | 9 | 11 | The current repair loop is a mixed negative control, not the main gain source. |
| Answer-shape repair off -> on | 64.2% | 61.5% | -2.7 pp | 9 | 13 | Answer-shape repair is a negative control; scorer-shape normalization is not carrying the gain. |

This table narrows the paper claim. FocusParse's advantage should be attributed
primarily to evidence localization, query-conditioned reranking, inspection,
and compact context expansion. Bounded verifier-directed repair remains useful
as an auditable control loop, and answer-shape repair remains useful as an
analysis target, but these matched runs do not support claiming either as a
positive accuracy mechanism.

### 6.5 Failure Taxonomy

The final FocusParse +4 row is correct on 91/148 examples and incorrect on
57/148 examples. The generated failure taxonomy is in
`results/paper/failure-taxonomy/` and uses the same primary failure classifier
as `scripts/diagnose_predictions.py`.

| Failure bucket | Count | Datasheet | Finance | Error share | All-row share |
| --- | ---: | ---: | ---: | ---: | ---: |
| Verifier unsupported | 26 | 16 | 10 | 45.6% | 17.6% |
| Partial localization | 12 | 6 | 6 | 21.1% | 8.1% |
| Localization miss | 8 | 5 | 3 | 14.0% | 5.4% |
| Reasoning/extraction | 7 | 4 | 3 | 12.3% | 4.7% |
| Lazy/no bbox | 4 | 3 | 1 | 7.0% | 2.7% |

This table sharpens the conclusion. The remaining errors are not primarily
caused by generic tool laziness: only four incorrect examples are lazy/no-bbox
cases. The largest bucket is verifier-unsupported answers after evidence
collection, followed by partial or missed localization. The next method work
should therefore improve evidence adjudication, answer-shape preservation, and
multi-region localization rather than merely adding more tools.

### 6.6 Mechanism: Lazy Answers And Cost

The base VLM and generic agent baseline rows are effectively lazy by design or
behavior: they often answer without using document tools or producing useful
region citations. ReAct uses tools more often, but at high latency and cost.
FocusParse uses a small number of structured tool actions and terminates with
lower lazy-answer rates.

This is why cost per correct answer is a better metric than raw call cost. A
single cheap full-page answer can be attractive until its error rate is included.
FocusParse pays for evidence construction, but that payment is targeted.

## 7. Qualitative Analysis

The working qualitative packet is
`docs/research/paper-draft/qualitative-evidence-packets.md`, and the figure
asset state is tracked in
`docs/research/paper-draft/qualitative-figure-manifest.md`. Same-revision
baseline predictions for the main qualitative figures are tracked in
`docs/research/paper-draft/qualitative-baseline-comparisons.md`. The examples below
are tied to the final matched n=148 parser-bench slice and the raw-verified
FocusParse +4 run under
`results/hf/paper/2026-05-24-paper-headline-v1/`. They are safe as current
mechanism examples. Cross-method qualitative baseline answers and composed
panel assets have now been generated for the two main figures.

### Finance Cross-Region Example

Candidate id: `fin-bis_qr_2025_mar-0050`. The question asks which country
satisfies both a panel-A GDP-growth condition and a panel-B bank-credit
condition. The gold answer is `Latvia`, with supporting pages `[8, 108, 109]`.
In the verified FocusParse run, the model answers correctly with page recall
`1.0`, BBox IoU `0.9999935`, and the tool sequence `inspect_region`,
`expand_context`, `expand_context`.

This example captures the paper thesis. A full-page model can see the page but
may not resolve small labels. A tight crop can read one panel but miss the other
panel or the country-abbreviation table. FocusParse's inspect-expand-reason
sequence is designed for exactly this case: inspect the readable chart regions,
expand them with linked context, then reason over a compact packet set.

The final-run viewer bundle contains the local page-overlay export for this
example, making it the strongest current candidate for a main-text finance
qualitative figure. A first composed panel is available at
`results/paper/qualitative-figure-panels/figure3-finance-latvia-evidence-binding.png`.

### Datasheet Cross-Page Success Example

Candidate id: `dat-JESD204B-Survival-Guide-0029`. The question asks the model
to count the number of K28.5 symbols on LANE0 between point 2 and point 3, then
corroborate the lane data path against an ADC processing block diagram and a
functional block diagram. The gold answer is `6`, with supporting pages
`[16, 73]` and an evidence page spread of `57`. In the final FocusParse run,
the model answers exactly with page recall `1.0`, BBox IoU
`0.9999916798927161`, and the tool sequence `inspect_region`,
`expand_context`.

This is the cleanest datasheet success figure in the final package. It shows
why evidence compaction matters for technical manuals: the answer depends on a
small high-resolution timing region, but the interpretation of that region is
validated by diagrams elsewhere in the document. A first composed panel is
available at
`results/paper/qualitative-figure-panels/figure4-datasheet-jesd204b-evidence-binding.png`.

### Datasheet Compaction Near-Miss

Candidate id: `dat-adrv9040-reference-manual-ug-2192-0032`. The question asks
which firmware file must be loaded first and what size is listed for it. The
gold answer is `ADRV9040_FW.bin, 641 kb`, with supporting pages `[10, 75, 114]`
and an evidence page spread of `104`. In the final FocusParse run, the
prediction is `ADRV9040_FW.bin`: the scorer marks the row correct, but the
answer omits the requested `641 kb` size field.

This example is no longer a clean positive result. It is still useful as an
analysis case because it exposes a field-preservation failure after evidence
selection. The system localized a useful file-name region, but the final answer
did not preserve every requested value from the cross-page evidence.

### Datasheet Near-Miss Visual Example

Candidate id:
`dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0052`.
The question asks whether `Q1 (HS)` or `Q2 (LS)` is the MOSFET positioned at the
top of a PCB layout near capacitors `C15-C18`. The gold answer is `Q1 (HS)`. In
the verified FocusParse run, the model answers correctly with page recall `1.0`
and a non-lazy inspect/expand trace, but the final BBox IoU is only `0.256295`.

This is useful as an honest visual-disambiguation case. The answer is right, but
the localization metric shows that precise crop placement can remain imperfect
even when packet context is enough for answer selection.

The final-run viewer resolves the page image. This example should remain an
analysis or appendix candidate with the low-IoU caveat explicit.

### Honest Failure Pattern

Current audits show that once localization is strong, the remaining failures are
often post-localization: verifier-unsupported final answers, wrong value
extraction from the right crop, answer-shape mistakes, row disambiguation, and
multi-field completion. This is useful for the conclusion. The paper should not
imply that FocusParse solves document QA. It should argue that evidence
construction moves the bottleneck downstream, from "where is the evidence?" to
"how do we read, adjudicate, and shape the answer from the right evidence?"

## 8. Limitations

1. The older 66.9% result still needs raw artifact recovery or rerun before it
   can replace the 61.5% matched result as the headline.
2. The canonical dataset slice is small: 148 examples, with 47 finance rows.
   Confidence intervals and variance discussion are required.
3. The public HF dataset surface has more rows than the FocusParse paper slice,
   so the paper must carefully explain filtering.
4. Current cost figures are point-in-time experimental costs from repo pricing
   tables, not a permanent provider-rate claim.
5. FocusParse is a harness, not a trained model. The natural next step is
   distillation from trajectories into a learned compact policy.
6. The current answer-shape repair ablation is negative: disabling
   answer-shape-specific repair improves the matched run from 61.5% to 64.2%.
   The paper should frame this as an over-correction risk, not as a gain source.

## 9. Conclusion

Dense finance and datasheet QA requires more than large VLMs and generic tools.
The system must find the right evidence, inspect it at the right resolution,
reconnect it to local context, compact it into a reasoner-readable form, and
verify that the answer is supported. FocusParse operationalizes this as a
structured evidence-packet harness. Current artifacts support a precise claim:
in the matched table on the pinned 148-row parser-bench slice, FocusParse +4
reaches 61.5% accuracy and substantially outperforms the base VLM and generic
tool-agent comparators while preserving strong localization.

The paper's final version should make a precise claim: FocusParse is not
valuable because it has more tools. It is valuable because it controls how tools
construct evidence.

## Submission TODOs

See `docs/research/paper-draft/submission-readiness-checklist.md` for the
table, figure, provenance, and rerun gates.

- Commit or externally archive the exact code/docs used to build the final
  table. A slim 44M review archive exists at
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32.tar.gz`,
  with a sibling `.tar.gz.sha256` checksum sidecar.
- Recover or reproduce `shape-normalizer-full-run1` only if the paper wants to
  supersede the verified 61.5% headline.
- Carry HF revision `3774c67f8b814392b6d04c939e904f749a3f52eb` and the final
  code SHA into the reproducibility table.
- Carry the exact qualitative examples, failure taxonomy, page images, crops,
  packet ids, and per-method answers into the selected venue template.
- Carry the existing confidence intervals from `headline_table.md` into the
  camera-ready table.
- Run a variance-controlled replicate for the final FocusParse row.
- Search/export from Zotero once the local Zotero Desktop app/profile/API is
  available.
- Convert this Markdown draft to the target venue format using
  `venue-template-conversion-audit.md` as the source-mapping checklist.
- Port `neurips-checklist-prep.md` into the target venue checklist once page
  and section references are stable.
- Use `source-pdf-and-asset-license-audit.md` to select the final artifact
  release mode before publicly distributing source-derived page/crop assets;
  the current source-safer package is
  `results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10.tar.gz`,
  with a sibling `.tar.gz.sha256` checksum sidecar.
