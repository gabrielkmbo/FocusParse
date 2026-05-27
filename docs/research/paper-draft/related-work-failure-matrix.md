# FocusParse Related-Work Failure Matrix

Date: 2026-05-24

Status: working matrix for the Related Work section. The purpose is not to
dismiss prior work, but to state exactly which part of the FocusParse thesis
each related-work family explains and which gap remains.

Live external-source checks for the closest papers, GitHub repos, and Hugging
Face datasets are recorded in
`docs/research/paper-draft/external-source-audit.md`.

## Matrix

| Family | Representative citations | What it explains | Remaining failure point for FocusParse |
| --- | --- | --- | --- |
| Layout and document parsing benchmarks | DocLayNet, PubTabNet, GTE/FinTabNet, OmniDocBench, MPDocBench-Parse, external ParseBench | Document pages contain structured regions; page parsing should be evaluated beyond plain OCR; tables/charts/layout need specialized annotations; MPDocBench-Parse stresses multi-page semantic continuity and hierarchy recovery; external ParseBench evaluates five agent-facing parsing dimensions over enterprise pages. | A complete or high-quality page or document parse does not by itself prove that a query-answering system selected the answer-supporting evidence for a question, attached the needed local context, and cited the supporting page/box. |
| Document and long-document QA | DocVQA, InfographicVQA, MMLongBench-Doc | Document QA requires multimodal reasoning over text, layout, and visual elements, sometimes across long context. | Long context can preserve document coverage while still blurring tiny labels, footnotes, or chart/table details; these benchmarks do not isolate inspect and expand as the mechanism under test. |
| Financial QA and RAG | FinQA, TAT-QA, FinanceBench, FinRAGBench-V | Financial questions often require numerical reasoning, table/text fusion, and evidence-grounded open-book answers. | Much of the finance lineage is text/table-centric or retrieval-centric; parser-bench stresses high-resolution visual region grounding, multi-region context collection, and page/crop citations in finance reports. |
| Chart and table QA | ChartQA, PlotQA, PubTabNet, GTE/FinTabNet | Charts and tables require visual structure recognition, numeric reading, and sometimes out-of-vocabulary answers. | Standalone chart/table tasks do not capture the long-PDF setting where a chart must be connected to captions, legends, footnotes, table references, symbol dictionaries, or neighboring panels. |
| Query-conditioned document systems | AgenticOCR, DocLens | It is wasteful and error-prone to parse or feed whole pages when only specific evidence is needed; agents can navigate to evidence; page-level chunking and poor evidence localization are named failure modes in the closest work. | Query-conditioned localization is necessary but not sufficient: FocusParse additionally studies typed evidence packets, role-labeled neighbor expansion, compaction, and bounded verifier-directed repair on region-grounded parser-bench rows. |
| Generic tool-using agents | ReAct and ReAct-style document agents | Reasoning/action loops let models gather observations from tools instead of answering in one shot. | The same flexibility can produce lazy termination, noisy transcripts, repeated irrelevant tool calls, and weak citations. FocusParse tests whether controlled evidence construction beats unconstrained tool access. |

## Paper Thesis Alignment

The paper should organize related work around the failure that FocusParse is
designed to address:

1. Full-page or long-context methods preserve coverage but lose tiny evidence.
2. Tight crops restore resolution but lose document semantics.
3. Generic tool loops can use OCR/crop tools but do not guarantee compact,
   answer-supporting evidence.
4. FocusParse contributes the missing middle object: a typed evidence packet
   that binds a readable region to the local context needed to interpret it.

## Current Source Refresh

The 2026-05-24 source refresh supports three paper-facing distinctions:

1. MPDocBench-Parse is a new multi-page parsing benchmark focused on practical
   document-level parsing, semantic continuity, hierarchy recovery, and visual
   content preservation.
2. External RunLlama `ParseBench` is a document parsing benchmark for agentic
   workflows, with HF/README claims around five dimensions: tables, charts,
   content faithfulness, semantic formatting, and visual grounding.
3. Gabriel's `parser-bench` is the paper dataset: citation-required visual QA
   over finance and datasheet PDFs, evaluated by answer correctness plus
   supporting page/box localization.
4. The closest method comparison is not "agentic versus non-agentic." It is
   whether the agent builds the right compact evidence object before final
   reasoning.

## Wording Guardrails

- Do not claim prior benchmarks are "wrong"; say they optimize a different
  target or leave a different failure mode exposed.
- Do not claim FocusParse solves long-document QA generally; it studies a
  concentrated high-resolution slice where evidence localization and context
  attachment are measurable.
- Do not equate Gabriel's `parser-bench` with external ParseBench. Use
  `parser-bench` for the local/HF dataset and `ParseBench` for the RunLlama
  paper.
- Do not overstate the 66.9% result until raw artifacts are recovered or rerun.
