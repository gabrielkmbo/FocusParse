# FocusParse Methods And Dataset Code Audit

Date: 2026-05-24

Status: source-grounded notes for the paper Methods and Dataset sections. This
file is intentionally implementation-facing; the paper draft should translate
these details into conference prose.

Latest refresh: current files under `src/focusparse/` and
`third_party/parser-bench/src/` were re-inspected on 2026-05-24 while preparing
the submission objective audit. The stage map and schema claims below remain
consistent with the current checkout.

## Parser-Bench Dataset

Primary sources:

- `third_party/parser-bench/README.md`
- `third_party/parser-bench/docs/benchmark_spec.md`
- `third_party/parser-bench/docs/taxonomy.md`
- `third_party/parser-bench/docs/highres_benchmark_spec.md`
- `third_party/parser-bench/src/utils/schema.py`
- `src/focusparse/eval/hf_loader.py`

Implementation-backed claims:

| Paper claim | Source evidence |
| --- | --- |
| Parser-bench is citation-required VQA over financial reports and technical datasheets. | Parser-bench README and benchmark spec define localization, reasoning, and citation as the three core requirements. |
| Each row is more than a question-answer pair. | `BenchmarkExample` includes `question`, `answer`, `answer_type`, `answer_unit`, `tolerance`, `supporting_pages`, `supporting_bboxes`, `alternate_bboxes`, `evidence_relations`, `multi_region_required`, `requires_visual`, `difficulty`, `question_family`, `stress_type`, `reasoning_chain`, and `evidence_page_spread`. |
| The schema supports answer and evidence scoring separately. | Parser-bench scoring computes answer correctness, page recall, and BBox IoU. FocusParse wraps the same semantics and adds evidence reward / lazy-answer accounting. |
| The public HF split is materialized before FocusParse evaluation. | `src/focusparse/eval/hf_loader.py::materialize_split()` writes `benchmark.jsonl` plus page PNGs under a local staging directory. |
| The paper slice filters pre-baked stress rows. | `src/focusparse/eval/hf_loader.py::_filter_stress_rows()` keeps only rows where `stress_type` is empty or `none`. |
| HF `validation` is the paper/test split in current FocusParse runs. | `src/focusparse/eval/hf_loader.py` documents that HF `validation` maps to the paper benchmark. |

Dataset wording to preserve:

Parser-bench should be described as a region-grounded evaluation for dense,
high-resolution documents, not as a generic document QA benchmark. Its
distinctive feature is that a model can be right or wrong along two separable
axes: answer content and evidence localization.

## FocusParse Harness

Primary sources:

- `src/focusparse/pipeline/events.py`
- `src/focusparse/pipeline/workflow.py`
- `src/focusparse/evidence/packet.py`
- `src/focusparse/pipeline/{planner,router,localizer,region_reranker,inspector,expander,reasoner,verifier}.py`
- `src/focusparse/eval/metrics.py`
- `src/focusparse/eval/scoring.py`

Implementation-backed stage map:

| Stage | Code contract | Paper interpretation |
| --- | --- | --- |
| Plan | `PlanEvent` contains `question_family`, `evidence_types`, `budget_class`, `routing_policy`, and caps for tools/crops/VLM calls. | Converts a broad document question into an evidence request and budget. |
| Route pages | `route_pages()` builds a recall-biased text FTS page set, defaulting to top-5 when page text exists and falling back to all pages when text is absent or empty. | Keeps page retrieval separate from evidence proof. |
| Localize | `propose_regions()` calls layout detection per routed page and emits normalized `RegionCandidate` boxes; failures become explicit full-page fallbacks unless eval config fails fast. | Turns pages into candidate visual regions and records fallback modes. |
| Rerank | `rerank_regions()` scores localizer boxes for query relevance and assigns `needed_for` roles plus missing-context hints. | Chooses evidence by question relevance, not detector confidence alone. |
| Inspect | `inspect_regions()` crops images, extracts native PDF text when possible, falls back to OCR, optionally adds multi-scale/zoom/context crops, and can run chart/table extraction on chart-like families. | Makes dense visual evidence readable before final reasoning. |
| Expand | `expand_context()` attaches bounded, role-labeled neighbors such as captions, legends, footnotes, headers, axes, and context windows. | Restores the local semantics that tight crops lose. |
| Answer | `answer_from_evidence()` sends only packet images/text and requires strict JSON with answer, packet citations, and confidence. | The reasoner consumes compact evidence packets rather than raw pages. |
| Verify | `verify_answer()` performs a support check and emits `accept`, `retry_localization`, `expand_context`, `abstain`, or `escalate_reasoner`. | The verifier is a bounded controller, not only a judge. |

Load-bearing method distinction:

FocusParse should not be framed as "ReAct with more tools." The code separates
tool use from answer generation through typed events and a hard packet boundary:
`QuestionEvent -> PlanEvent -> PagesEvent -> RegionsEvent -> EvidenceEvent ->
AnswerEvent -> VerdictEvent`. The reasoner receives `list[EvidencePacket]`, not
raw pages or arbitrary scratchpad state.

## Evidence Packet Contract

Primary source: `src/focusparse/evidence/packet.py`.

An `EvidencePacket` can carry:

- `packet_id` for citation;
- page number and normalized bbox;
- region type;
- page thumbnail;
- tight local crop;
- optional context crop;
- optional multi-scale crops with `tight`, `context`, `chart_context`, or
  `zoomed` scale labels;
- linked neighbor crop refs;
- OCR and native text snippets;
- optional chart CSV and extraction confidence;
- linked neighbor role labels;
- evidence edges;
- tool provenance and confidence.

Paper interpretation:

The packet is the compaction object. It is the mechanism that allows the system
to preserve high-resolution detail and semantic neighbors without giving the
reasoner an entire page or entire document.

## Experiment/Metric Implications

Primary sources:

- `src/focusparse/eval/scoring.py`
- `src/focusparse/eval/metrics.py`
- `third_party/parser-bench/src/eval/scoring.py`

Paper-safe metric definitions:

- Accuracy: answer scorer matched to `answer_type` (`numeric`, `exact_match`,
  `multiple_choice`, `boolean`, `unanswerable`).
- Page recall: fraction of gold supporting pages cited/found.
- BBox IoU: best overlap between predicted and gold supporting boxes.
- Evidence reward: FocusParse-specific localization-aware reward with a
  lazy-answer penalty.
- Lazy answer rate: non-use of useful evidence/tool calls or missing predicted
  boxes, depending on the run record.
- Cost per correct: total run cost divided by correct examples, with bootstrap
  confidence intervals available in aggregate metrics.

Paper implication:

The central result should not be reported as accuracy alone. The claim is about
why accuracy changes: page recall, BBox IoU, lazy-answer rate, and qualitative
packet traces are the mechanism evidence.
