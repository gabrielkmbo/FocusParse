# FocusParse Venue And Submission Plan

Date: 2026-05-24

Status: venue-framing plan refreshed against official venue pages on
2026-05-24. Dates and policies are time-sensitive; re-check the target call
again before committing to any submission.

## Current Timing Reality

As of 2026-05-24, the major 2026 main-conference deadlines named in the project
goal have passed. The realistic near-term route is a NeurIPS 2026 workshop
paper; the strongest archival full-paper routes are 2027 main or evaluation
tracks.

| Venue | 2026 status from official source | FocusParse implication |
| --- | --- | --- |
| CVPR 2026 | Official paper deadline was 2025-11-13 AoE; supplementary deadline was 2025-11-20 AoE; final decisions were 2026-02-20. The conference runs 2026-06-03 to 2026-06-07 in Denver. | Not available for this paper cycle. Use CVPR-style framing for a future document vision / multimodal reasoning venue, especially if emphasizing high-resolution visual grounding and BBox IoU. |
| ACL 2026 | Main paper deadline was 2026-01-05 via ARR; system-demonstration deadline was 2026-02-27 AoE; industry-track deadline was 2026-02-14 AoE; conference is 2026-07-02 to 2026-07-07. | 2026 ACL cycles are closed. ACL-style framing remains useful if the paper is pitched as document QA / multimodal RAG with evidence faithfulness. |
| ICML 2026 | Official full paper deadline was 2026-01-28 AoE; conference is 2026-07-06 to 2026-07-11. | Main conference closed. Use ICML 2027 only if the method contribution is sharpened with ablations and a general agentic-evaluation argument. |
| ICLR 2026 | Official full paper deadline was 2025-09-24 AoE; ICLR 2026 uses a 9-page submission limit and double-blind review. | Closed. Consider ICLR 2027 if the final result package is strong by late summer/fall 2026 and the claim is method-centric. |
| NeurIPS 2026 main / ED | Main and Evaluations & Datasets full paper deadlines were 2026-05-06 AoE. ED explicitly covers evaluation protocols, benchmarks, audits, and tools, but the 2026 archival deadline has passed. | The 2026 main/ED tracks are closed. Keep the ED framing because it is the cleanest archival full-paper fit for NeurIPS 2027. |
| NeurIPS 2026 workshops | Workshop proposals close 2026-06-06 AoE; accepted workshops are notified 2026-07-11 AoE; the suggested workshop contribution date is 2026-08-29 AoE; mandatory workshop accept/reject notification is 2026-09-29 AoE. | Best near-term target. Track accepted workshops after 2026-07-11, then submit the workshop-length paper to the best-fit call if final table, figures, and artifact package are ready by August. |

## Recommended Target Order

1. NeurIPS 2026 workshop paper, primary near-term target.
2. NeurIPS 2027 Evaluations & Datasets or main track, strongest archival
   target if parser-bench and FocusParse are polished into a benchmark/method
   package.
3. ICLR 2027 or ICML 2027 main/workshop, if the final contribution is framed as
   a general agentic evaluation/method for multimodal document reasoning.
4. ACL / EMNLP / NAACL 2027, if the final contribution is framed as multimodal
   document QA / RAG with evidence grounding.
5. CVPR / ICCV / ECCV workshop or main-track style venue, if the final emphasis
   is document image analysis, visual grounding, and high-resolution crop
   evidence.

## Best Framing By Venue Family

### NeurIPS Evaluations & Datasets

Best title shape:

```text
Evidence Packets for Evaluating Agentic Document QA on High-Resolution Finance and Datasheet PDFs
```

Pitch:

FocusParse plus parser-bench is an evaluation story: existing document parsing
and long-context QA metrics obscure whether the model actually found the right
region. Parser-bench makes answer correctness and evidence localization
measurable, and FocusParse tests whether structured evidence construction moves
the metric.

Needed before submission:

- pinned HF dataset revision;
- final all-method table under one code SHA;
- confidence intervals for every headline cell;
- public artifact package with `run.json`, `per_example.jsonl`, configs, and
  qualitative figures;
- clear statement that the dataset is concentrated, not domain-general.

### NeurIPS / ICLR / ICML Main Or Workshop

Best title shape:

```text
Inspect, Expand, Then Reason: Structured Evidence Construction for Dense Document QA
```

Pitch:

The contribution is a method/harness: a controlled stage machine outperforms
unstructured tool use because it forces the reasoner through compact,
typed evidence packets.

Needed before submission:

- same-code comparison against Base VLM, ReAct, and generic agent baselines;
- ablations isolating inspect only, inspect+expand, no rerank, no verifier
  repair, and no answer-shape repair;
- mechanism table showing BBox IoU, page recall, lazy-answer rate, and
  cost/correct;
- at least two strong qualitative figures with real crop assets.

### ACL / EMNLP / NAACL

Best title shape:

```text
Citation-Grounded Multimodal Document QA Requires Evidence Packet Construction
```

Pitch:

The contribution is document QA/RAG: answer quality in finance and datasheets
depends on grounded evidence selection, not just retrieval, OCR, or long
context. The paper should emphasize answer/evidence faithfulness and failure
analysis.

Needed before submission:

- stronger related-work section around DocVQA, FinQA, TAT-QA, FinanceBench,
  FinRAGBench-V, and multimodal RAG;
- a citation-grounding error taxonomy;
- careful language about not solving general NLP document QA;
- Zotero-backed bibliography and hallucinated-reference check once Zotero
  Desktop/API is available.

### CVPR / ICCV / ECCV Workshop Or Main-Track Style

Best title shape:

```text
Region-Grounded Evidence Packets for High-Resolution Visual Document Question Answering
```

Pitch:

The contribution is visual grounding in document images. The strongest visual
story is that page-level models and generic tool agents fail to produce usable
region evidence, while FocusParse creates high-resolution packet-level crops
with context.

Needed before submission:

- visual figures with page overlays and crops;
- strong BBox IoU comparison against baselines;
- explicit connection to document layout, chart/table QA, and visual grounding
  benchmarks;
- a clear explanation of why finance/datasheet PDFs are a high-resolution
  visual reasoning setting.

## Near-Term NeurIPS Workshop Plan

The practical near-term path is:

1. By 2026-06-06: optionally track workshop-proposal announcements, but do not
   spend effort writing a workshop proposal unless there is an organizer path.
   The paper path starts after accepted workshops are announced.
2. On or after 2026-07-11: watch for accepted NeurIPS workshops and shortlist
   those on multimodal agents, document understanding, RAG/evaluation,
   data-centric AI, reliable AI systems, or tool-using evaluation.
3. By mid-July 2026: freeze the paper claim around the verified 61.5% matched
   table unless the documented 66.9% checkpoint is recovered or rerun.
4. By late July 2026: package/archive the all-method table, result manifest,
   diagnostics, and final code/doc snapshot.
5. By early August 2026: export the figure package and write the final
   workshop-length version.
6. By the suggested workshop contribution date, 2026-08-29 AoE: submit to the
   best-fit accepted NeurIPS workshop, unless the selected workshop posts a
   different official paper deadline.

## Submission Package Checklist

Minimum workshop submission:

- `focusparse-submission-draft.md` converted to the workshop template;
- `venue-template-conversion-audit.md` updated with the selected call URL,
  author-kit URL, page limit, anonymity policy, checklist policy, and compile
  result;
- final main table or explicit conservative-result table;
- dataset table with pinned HF revision;
- one strong pipeline/evidence-packet schematic;
- Latvia qualitative figure with real page/crop assets;
- bibliography checked against primary sources;
- public code/dataset links or anonymized equivalents depending on venue
  policy.

Stronger conference submission:

- all workshop items;
- final all-method table with confidence intervals;
- ablation table isolating inspect, expand, rerank, verifier repair, and
  answer-shape repair;
- generated failure taxonomy counts from `per_example.jsonl`;
- two to three qualitative figures;
- artifact README that allows another researcher to reproduce the table.

## Source Links Checked

- CVPR 2026 conference overview:
  `https://cvpr.thecvf.com/Conferences/2026`
- CVPR 2026 call for papers:
  `https://cvpr.thecvf.com/Conferences/2026/CallForPapers`
- CVPR 2026 author guidelines:
  `https://cvpr.thecvf.com/Conferences/2026/AuthorGuidelines`
- ACL 2026 main conference:
  `https://2026.aclweb.org/calls/main_conference_papers/`
- ACL 2026 system demonstrations:
  `https://2026.aclweb.org/calls/system_demonstration/`
- ACL 2026 industry track:
  `https://2026.aclweb.org/calls/industry_track/`
- ICML 2026 call for papers:
  `https://icml.cc/Conferences/2026/CallForPapers`
- ICLR 2026 author guide:
  `https://iclr.cc/Conferences/2026/AuthorGuide`
- NeurIPS 2026 dates:
  `https://neurips.cc/Conferences/2026/Dates`
- NeurIPS 2026 main call:
  `https://neurips.cc/Conferences/2026/CallForPapers`
- NeurIPS 2026 main track handbook:
  `https://neurips.cc/Conferences/2026/MainTrackHandbook`
- NeurIPS 2026 Evaluations & Datasets call:
  `https://neurips.cc/Conferences/2026/CallForEvaluationsDatasets`
- NeurIPS 2026 Evaluations & Datasets scope blog:
  `https://blog.neurips.cc/2026/03/23/introducing-the-evaluations-datasets-track-at-neurips-2026/`
- NeurIPS 2026 workshops call:
  `https://neurips.cc/Conferences/2026/CallForWorkshops`
- NeurIPS 2026 workshop guidance:
  `https://neurips.cc/Conferences/2026/WorkshopsGuidance`
