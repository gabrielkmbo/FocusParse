# FocusParse Paper Goal And Draft Plan

Date: 2026-05-22
Status: first paper-scoping pass from the active goal, slide deck, repo memory,
core code, parser-bench submodule, Hugging Face page, GitHub metadata, and
related-work search. This is the paper control document; the companion prose
draft lives in `docs/research/paper-draft/focusparse-paper-draft.md`.

## Active Goal

Write a research-level FocusParse paper suitable for a workshop or conference
submission path such as CVPR, NeurIPS, ICLR, ICML, ACL, EMNLP, or a document-AI /
multimodal-RAG workshop.

Core thesis:

> On concentrated, high-resolution finance and technical datasheet documents,
> strong document QA is limited by evidence construction, not only by model size
> or tool availability. FocusParse improves over base VLM and generic agent
> baselines because it localizes evidence, inspects it at readable resolution,
> expands it with linked context, compacts it into typed evidence packets, and
> verifies support before final answer selection.

The paper should have the conventional structure:

1. Introduction / motivation
2. Related work, with explicit failure points
3. Methods, covering both the FocusParse harness and the parser-bench dataset
4. Experiments and results
5. Conclusion / analysis

## Candidate Titles

- FocusParse: Evidence-Packet Construction for High-Resolution Document QA
- Inspect, Expand, Then Reason: A Structured Harness for Dense Document QA
- Localized Parsing of Complex Documents with Typed Evidence Packets

## What The Slide Deck Already Establishes

Source inspected:
`/Users/gabrielbo/Downloads/FocusParse Research Refresh - Google Slides.pdf`

The deck is 29 pages. The strongest paper spine is:

- Motivation: the answer is often a tiny visual detail inside a long PDF.
- Core tradeoff: full pages preserve context but lose resolution; tight crops
  preserve readability but lose captions, legends, headers, axis labels, and
  footnotes.
- Related-work gap: existing methods cover pieces of the evidence problem, but
  not reliable multi-piece context assembly before reasoning.
- Method: FocusParse runs `plan -> route -> localize -> inspect -> expand ->
  answer -> verify`.
- Main mechanism claim: targeted inspection plus context expansion gives the
  reasoner an organized evidence packet, not a whole messy PDF.
- Dataset story: parser-bench is region-grounded QA, not page transcription; a
  row stores question, answer, page ids, evidence boxes, difficulty/stress
  metadata, and answer tolerance.
- Qualitative anchor: the Latvia finance example requires panel A threshold,
  panel B threshold, country labels, and footnotes.

The deck currently uses the strong result:

| Metric | Slide value |
| --- | ---: |
| FocusParse four-tool accuracy | 66.9% |
| Base VLM accuracy | 47.3% |
| Coding loop accuracy | 25.7% |
| DocLens-style proxy accuracy | 16.9% |
| AgenticOCR-style proxy accuracy | 16.2% |
| ReAct two-tool accuracy | 12.2% |
| ReAct four-tool accuracy | 10.1% |
| Page recall | 0.949 |
| BBox IoU | 0.881 |
| Lazy rate | 0.020 |

Before those exact slide numbers go into the paper, recover or rerun the raw
`shape-normalizer-full-run1` artifact so the paper can cite `run.json`,
`per_example.jsonl`, code SHA, dataset revision, and per-example qualitative
evidence. The docs record this as a validated 99/148 result, but the raw
artifact has previously been easy to conflate with nearby 60.1% and 62.2% runs.

## Repo-Verified Method Contracts

FocusParse is already built around the paper's central mechanism.

Load-bearing code:

- `src/focusparse/pipeline/workflow.py`: top-level state machine, including
  planner, router, localizer, reranker, inspector, expander, reasoner, verifier,
  and verifier-directed retry control.
- `src/focusparse/evidence/packet.py`: `EvidencePacket` is the reasoner boundary.
  The reasoner receives typed packets, not raw pages.
- `src/focusparse/pipeline/inspector.py`: constructs answerable evidence packets
  via crop rendering, native text extraction, OCR fallback, visual OCR, context
  crops, optional auto-zoom, and optional chart extraction.
- `src/focusparse/pipeline/expander.py`: attaches role-labeled neighbor context
  such as captions, footnotes, legends, axis labels, titles, headers, row/column
  headers, and context windows.
- `src/focusparse/tools/inspect_region.py`: exactly three modes, `image`,
  `element`, and `region`, producing cached high-resolution crops and optional
  OCR/sub-layout observations.
- `src/focusparse/eval/hf_loader.py`: materializes Hugging Face parser-bench
  rows into local image/JSONL staging and filters stress variants for the
  canonical FocusParse evaluation slice.
- `third_party/parser-bench/src/utils/schema.py`: dataset schema includes domain,
  answer type, supporting pages, supporting boxes, alternate boxes, evidence
  relations, difficulty axes, question family, stress type, and evidence spread.

Paper framing:

FocusParse should not be described as "a ReAct agent with tools." It is a
structured evidence-construction harness whose key unit is a typed, compact
`EvidencePacket`. ReAct is a comparator.

## Dataset Positioning

Two distinct entities must not be confused:

- `gabrielbo/parser-bench`: Gabriel's HF dataset used by FocusParse. It is
  citation-required visual QA over high-resolution finance and technical
  datasheet documents.
- `ParseBench` arXiv 2604.08538: RunLlama's external benchmark paper for
  document parsing systems. It is related work, not the same dataset.

Current public HF page for `gabrielbo/parser-bench` shows image+text parquet data
with train/validation/test splits and fields such as `domain`, `question`,
`answer`, `answer_type`, `page_images`, `supporting_pages`,
`supporting_bboxes`, `evidence_relations`, `difficulty_*`, `question_family`,
and `stress_type`.

The FocusParse paper slice is the canonical post-filter validation set used in
the slide deck and prior results:

| Slice | Rows | Datasheet | Finance | Note |
| --- | ---: | ---: | ---: | --- |
| Canonical FocusParse paper slice | 148 | 101 | 47 | Stress rows filtered; used by headline evals |

For submission, pin and report:

- HF dataset revision, e.g. the slide deck records `3774c67`.
- Code commit SHA.
- Exact materialization command.
- Exact post-filter row count.
- Stress-filter logic and rationale.
- Any duplicate-row handling.

## Quantitative Evidence Inventory

See `docs/research/paper-draft/artifact-provenance-audit.md` for the current
paper-readiness distinction between raw artifact-verified results, documented
but locally missing results, and diagnostic/slice evidence.

### Conservative all-method table

`docs/research/2026-05-12-scientific-recalibration-and-experiment-plan.md`
records the clean seven-row n=148 comparison:

| Method | Accuracy | Cost/correct | Mean latency | Mean bbox IoU | Page recall | Lazy rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Base VLM | 37.8% | $0.0119 | 3.01s | 6.1% | 83.8% | 100.0% |
| ReAct +2 | 13.5% | $0.1846 | 16.15s | 31.8% | 78.2% | 19.6% |
| ReAct +4 | 14.2% | $0.2403 | 21.11s | 29.3% | 75.0% | 24.3% |
| Agent baseline +2 | 8.1% | $0.1244 | 5.42s | 0.0% | 0.0% | 100.0% |
| Agent baseline +4 | 6.8% | $0.1535 | 5.82s | 0.0% | 0.0% | 100.0% |
| FocusParse +2 | 50.0% | $0.0153 | 2.52s | 70.8% | 80.4% | 9.5% |
| FocusParse +4 | 43.9% | $0.0176 | 2.53s | 66.1% | 76.9% | 11.5% |

This table supports the architecture claim:

- FocusParse beats Base VLM overall.
- FocusParse beats ReAct and generic agent baselines by a wide margin with the
  same tool-count axis.
- Generic agents do not improve simply by adding tools.
- Mechanism signal is strongest in region grounding: FocusParse IoU is much
  higher than ReAct, Base VLM, or the agent baseline.

This table does not support the stronger claim that FocusParse +4 always beats
FocusParse +2. The paper should frame tool count as secondary; the architecture
and evidence-packet construction are the main intervention.

Current artifact caveat: the research memo points to
`results/hf/headline-v1-rebaseline-v2/headline_table.json`, but that directory
is not present in the current worktree. A diagnostics report for `rebaseline-v2`
is present, and older raw headline tables are present with different values.
Regenerate the final all-method table from raw artifacts before submission.

### Stronger 65%+ candidate table

`docs/research/2026-05-15-harness-65plus-post-evidence-iteration.md` records:

| Run | Correct | Accuracy | Datasheet | Finance | Cost/correct | Latency | Page recall | BBox IoU | Lazy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `shape-normalizer-full-run1` | 99/148 | 66.9% | 71/101 | 28/47 | $0.0232 | 3.70s | 0.949 | 0.881 | 0.020 |

Use this as the target headline only after one of these is true:

- the raw run artifact is recovered locally or from external storage, or
- the run is reproduced on the pinned dataset/code path with matching
  `run.json`, `per_example.jsonl`, and paper-table export.

## Related Work Map

Candidate citations already found from primary or near-primary sources:

| Work | How it relates | Failure point / contrast for FocusParse |
| --- | --- | --- |
| AgenticOCR: Parsing Only What You Need for Efficient RAG, arXiv 2602.24134 | Query-driven, on-demand OCR/visual document parsing; argues against page-level chunking because full pages add extraneous context and compress salient evidence. | Strongly aligned with query-conditioned inspection, but FocusParse emphasizes typed evidence packets and explicit neighbor expansion for captions/legends/headers/footnotes before reasoning. |
| DocLens: Tool-Augmented Multi-Agent Long Visual Document Understanding, arXiv 2511.11552 | Tool-augmented localization from documents to pages/elements plus sampling/adjudication. | Close architectural neighbor; FocusParse should distinguish itself by controlled state-machine stages, compact typed evidence packets, verifier-directed repair, and parser-bench's high-resolution finance/datasheet evidence labels. |
| ParseBench: A Document Parsing Benchmark for AI Agents, arXiv 2604.08538 | External document parsing benchmark focused on semantic correctness across tables, charts, content faithfulness, formatting, and grounding. | Use as motivation that agent-facing parsing needs semantic/grounded correctness; distinguish Gabriel's parser-bench as question-answer/evidence-localization over finance/datasheets. |
| OmniDocBench, arXiv 2412.07626 / CVPR 2025 | Comprehensive PDF parsing benchmark with diverse document sources, layout categories, and attribute labels. | Good benchmark coverage, but FocusParse's claim is QA from localized evidence, not end-to-end page parsing fidelity. |
| DocLayNet, arXiv 2206.01062 / KDD 2022 | Large human-annotated document layout analysis dataset. | Layout detection is a stage/tool dependency, not the research product; FocusParse evaluates whether layout-grounded evidence helps QA. |
| DocVQA, arXiv 2007.00398 / WACV 2021 | General document visual question answering over document images. | Establishes purpose-driven document QA, but is less focused on high-resolution region citations and evidence packets. |
| InfographicVQA, arXiv 2104.12756 | VQA over infographic documents requiring layout, text, graphics, and data-visualization reasoning. | Useful bridge for mixed visual/text reasoning, but parser-bench embeds such reasoning in longer finance/datasheet PDFs with explicit evidence boxes. |
| MMLongBench-Doc, arXiv 2407.01523 / NeurIPS 2024 Datasets and Benchmarks | Long-context multimodal document understanding with cross-page and multi-source evidence. | Strong long-document context, but FocusParse isolates the evidence-localization and compaction mechanism on dense technical domains. |
| FinQA, ACL 2021; TAT-QA, ACL 2021; FinanceBench, arXiv 2311.11944 | Financial QA and numerical reasoning over financial reports, hybrid table/text contexts, and open-book filings. | Good finance-domain motivation; FocusParse adds visual region grounding and citation boxes over high-resolution pages. |
| FinRAGBench-V, arXiv 2505.17471 | Multimodal financial RAG with visual citation. | Closest finance/citation benchmark; FocusParse's contrast is region-grounded harness mechanics and datasheet+finance evidence packets. |
| ChartQA, arXiv 2203.10244 / Findings ACL 2022 | Chart question answering with visual and logical reasoning. | Useful chart-QA precursor, but does not force full-document page routing, citation boxes, and linked cross-region evidence in dense PDFs. |
| PlotQA, arXiv 1909.00997 / WACV 2020 | Scientific plot QA with real-valued and OOV answers. | Important for chart reasoning history, but synthetic/plot-focused compared with full enterprise/datasheet PDFs. |
| PubTabNet, arXiv 1911.10683 | Large image-based table recognition dataset with HTML structure. | Table recognition is narrower than parser-bench's mixed visual QA with citations and cross-region evidence. |
| GTE / FinTabNet, arXiv 2005.00589 / WACV 2021 | Joint table identification and cell-structure recognition with financial/scientific table annotations. | Important financial-table lineage; narrower than answering from linked visual/text evidence in whole PDFs. |
| ReAct, arXiv 2210.03629 / ICLR 2023 | Generic reasoning/action loop for tool use. | Baseline family for "tools are available"; FocusParse argues structure and evidence packets are the key intervention. |

Zotero blocker:

The local Zotero helper could not find a Zotero profile, the local API at
`127.0.0.1:23119` was closed, and `open -a Zotero` could not find a Zotero
application. To use Zotero for the bibliography pass, install or start Zotero
Desktop on this machine/profile, then rerun:

```bash
python3 /Users/gabrielbo/.codex/plugins/cache/openai-curated/zotero/6188456f/skills/zotero/scripts/zotero.py status --json
```

After Zotero is available, search/export additional candidate citations into the
paper `references.bib`.

## Proposed Paper Structure

### 1. Introduction / Motivation

Claim the problem precisely:

- Enterprise and technical documents are increasingly inputs to agents.
- Dense finance reports and datasheets contain answers in small high-resolution
  regions.
- Full-page VLM inference loses small details under visual-token compression.
- Tight local crops lose context, especially captions, legends, axis labels,
  table headers, footnotes, and cross-page continuation.
- Generic agent loops can call tools, but free-form exploration does not
  reliably sharpen evidence.

Contribution bullets:

1. A region-grounded high-resolution document QA benchmark slice over finance
   and technical datasheets.
2. FocusParse, a structured harness that inspects, expands, compacts, and
   verifies evidence before final reasoning.
3. A controlled comparison against Base VLM, ReAct, and generic agent baselines
   under the same reasoner, tools, and parser-bench scorer.
4. Mechanism analysis showing accuracy tracks evidence localization, BBox IoU,
   lazy-answer rate, and linked-context construction.

### 2. Related Work

Organize by failure mode rather than by chronology:

- Document parsing benchmarks: ParseBench, OmniDocBench, DocLayNet, PubTabNet,
  GTE/FinTabNet-style table datasets.
- Document and financial QA: DocVQA, InfographicVQA, MMLongBench-Doc, FinQA,
  TAT-QA, FinanceBench, FinRAGBench-V.
- Chart and visual QA: ChartQA, PlotQA, chart-specific benchmarks.
- Agentic / tool-using document systems: AgenticOCR, DocLens, generic ReAct,
  coding-agent style visual tools.
- Retrieval and visual RAG: page chunking, reranking, localized parsing.

Each paragraph should end with the gap FocusParse targets: not just finding
evidence, but assembling the exact linked context required for the answer.

### 3. Methods

Split this section into dataset and harness.

Dataset / parser-bench:

- Source documents: finance reports and technical datasheets.
- Row schema: question, gold answer, answer type, tolerance/unit, supporting
  pages, supporting boxes, alternate boxes, evidence relations, difficulty
  axes, question family, stress type.
- Eval slice: canonical n=148 post-filter split, 101 datasheet / 47 finance.
- Why region labels matter: the same run can be scored for answer correctness
  and localization quality.

FocusParse harness:

- Pipeline: `plan -> route_pages -> localize -> rerank -> inspect ->
  expand_context -> answer -> verify`.
- Evidence packet contract: crop refs, linked neighbor refs/types, snippets,
  chart CSV, provenance, confidence.
- Inspect stage: `inspect_region` modes (`image`, `element`, `region`),
  native text, OCR, visual crops, optional zoom.
- Expand stage: query-conditioned neighbor attachment, role-labeled context,
  bounded budgets, verifier-targeted repairs.
- Reasoner: answers from compact evidence packet set, not raw pages.
- Verifier: support check plus `next_action` for repair/abstention.

### 4. Experiments / Results

Core experiment:

- Same dataset, same reasoner, same protocol, same scoring.
- Methods: Base VLM, ReAct +2/+4, Agent baseline +2/+4, FocusParse +2/+4.
- Metrics: accuracy, cost/correct, latency, page recall, BBox IoU, lazy rate.

Ablations:

- +2 vs +4 tools.
- `expand_context` on/off.
- verifier-directed repair on/off.
- chart/table extraction if stable.
- answer-shape normalization separately from evidence-localization mechanics.

Mechanism analysis:

- Correlate answer correctness with BBox IoU, page recall, linked-context count,
  lazy rate, verifier supportedness, and answer-changed-after-tool.
- Separate failure buckets: localization miss, partial localization, right
  region/wrong extraction, answer-shape/scorer mismatch, verifier false accept,
  infrastructure null.

Qualitative cases:

- Latvia finance cross-region example from the slide deck.
- Datasheet cross-page / cross-region linked evidence example.
- At least one failure case where FocusParse localizes correctly but extracts
  the wrong value; this keeps the analysis honest.

### 5. Conclusion / Analysis

Emphasize:

- Structured evidence construction is the intervention.
- More tools are not enough; unconstrained tool loops can be slower, costlier,
  and less grounded.
- The remaining bottleneck after strong localization is often extraction,
  answer shaping, or same-evidence chart/table disambiguation.
- The natural next step is a learned policy trained from FocusParse trajectories,
  not a broader generic agent loop.

## Submission Positioning

Best fits:

- CVPR / ICCV / ECCV workshop on document image analysis, multimodal agents, or
  visual reasoning.
- NeurIPS / ICLR / ICML workshop on agents, RAG, multimodal systems, or evals.
- ACL / EMNLP / Findings if framed as document QA / multimodal RAG with strong
  dataset and evaluation methodology.

Full main-conference readiness requires:

- Recovered/rerun artifact for the 66.9% headline.
- Stable pinned dataset revision.
- Bibliography with direct citations and BibTeX. A primary-source draft
  bibliography exists, but Zotero export is still blocked until Zotero Desktop
  and the local Zotero API are available on this profile.
- At least one replicated run or variance-control argument for the headline
  table.
- A crisp distinction from AgenticOCR and DocLens.
- A crisp distinction between Gabriel's `parser-bench` and external RunLlama
  `ParseBench`; the current paper-draft audit has this separation.

## Immediate Next Steps

1. Resolve result provenance: recover or rerun `shape-normalizer-full-run1` and
   export `run.json`, `per_example.jsonl`, `headline_table.{md,json}`, and
   qualitative trace evidence.
2. Rematerialize the pinned HF revision into a clean paper staging directory and
   record exact row/domain counts.
3. Install/start Zotero Desktop, then search/export related papers into a
   BibTeX file.
4. Create a paper directory with `paper.md` or LaTeX skeleton plus
   `references.bib`. Current draft package:
   `docs/research/paper-draft/focusparse-submission-draft.md` plus
   `docs/research/paper-draft/references.bib`.
5. Finalize the related-work matrix and external-source audit with pinned
   external URLs, revisions, or archive DOIs.
6. Select 3-5 qualitative examples and capture page images/crops from real
   traces; Latvia is draft-figure ready, while ADRV9040 and Infineon need crop
   regeneration.
7. Use `docs/research/paper-draft/venue-submission-plan.md` to select the
   target workshop or conference once deadlines and accepted workshops are
   known.
8. Decide whether the first draft uses the conservative all-method table or the
   stronger 66.9% table as the main result.
