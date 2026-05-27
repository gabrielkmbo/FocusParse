# FocusParse Paper Objective Completion Audit

Date: 2026-05-24

Status: current-state audit against the active paper goal. This file is not a
new scope definition; it records what the current workspace proves, what it
does not prove yet, and which artifacts should move before the goal can be
called complete.

## Objective Requirements

| Requirement from goal | Current evidence | Status | Next gate |
| --- | --- | --- | --- |
| Write a research-level paper suitable for a workshop or conference path such as CVPR, NeurIPS, ICLR, ICML, ACL. | `focusparse-submission-draft.md`, `focusparse-paper-draft.md`, `latex/main.tex`, and compiled `latex/main.pdf` exist. `venue-submission-plan.md` maps the venue families and timing, `venue-template-conversion-audit.md` maps the current source into the next official template, and `neurips-checklist-prep.md` drafts checklist/disclosure answers. | Substantial draft exists; not yet submit-ready. | Select the target workshop/conference, convert to its author kit, and check anonymity, page limit, artifact, checklist, and supplementary-material rules. |
| Base the paper on the dataset and harness created in this project. | `methods-and-dataset-code-audit.md`, `dataset-characterization.md`, `pinned-dataset-provenance.md`, `final-headline-run-summary.md`, and the final result root connect parser-bench, FocusParse, and the n=148 run. | Achieved for draft/provenance level. | Archive or commit the exact code/docs used for submission. |
| Make the central argument that high-resolution finance and datasheet QA depends on inspect, expand, evidence localization, compaction, and evidence connection. | Abstract, Introduction, Related Work, Methods, Results, Conclusion, `related-work-failure-matrix.md`, qualitative figure docs, 3-row pure-ablation smoke checks, and the n=148 no-expand/no-rerank/verifier-repair/answer-shape-repair ablations all now use the evidence-packet thesis. | Achieved for the conservative 61.5% paper claim. | Keep the verifier-repair and answer-shape repair ablations framed as mixed/negative controls, not gain sources. |
| Use standard structure: introduction/motivation, related works with failure points, methods, experiments/results, conclusion/analysis. | The Markdown and LaTeX drafts follow this structure and include a failure-mode Related Work section. | Achieved structurally. | Tighten to target venue length and style. |
| Explain both the FocusParse harness and parser-bench dataset in Methods. | `focusparse-submission-draft.md`, `focusparse-paper-draft.md`, `latex/main.tex`, and `methods-and-dataset-code-audit.md` describe the eight-stage harness, EvidencePacket boundary, and parser-bench schema/slice. | Achieved at draft level. | Finalize figures/schematic and ensure all method claims cite stable code/docs. |
| Understand and use the detailed slide deck. | `2026-05-22-focusparse-paper-goal-and-draft-plan.md` records the 29-slide deck review; the paper draft preserves the full-page versus crop tradeoff, inspect/expand mechanism, Latvia qualitative anchor, and dataset framing. | Achieved for paper framing. | Avoid using the deck's 66.9% result as a headline unless raw artifacts are recovered or rerun. |
| Deeply understand the FocusParse codebase and parser-bench codebase. | `methods-and-dataset-code-audit.md` maps paper claims to `src/focusparse/pipeline/*`, `src/focusparse/evidence/packet.py`, `src/focusparse/eval/*`, and `third_party/parser-bench/src/utils/schema.py`; current inspection confirms those files exist. | Achieved for current paper-method explanation. | Keep this audit updated if method code changes before submission. |
| Use Hugging Face and GitHub sources for FocusParse/parser-bench and distinguish external ParseBench. | `external-source-audit.md`, `pinned-dataset-provenance.md`, and `citation-map.md` record HF/GitHub source checks and the `ParseBench` versus `parser-bench` distinction. | Achieved for current draft. | Replace moving URLs with archive DOI/commit references where possible. |
| Use Zotero to find/cross-check related papers. | Zotero helper status reports no profile/version and connection refused at `127.0.0.1:23119`; `bibliography-readiness-audit.md` and `external-source-audit.md` record this blocker. | Not achieved; blocked by local Zotero availability. | Start/install Zotero Desktop with local API enabled, then export/search the library and reconcile `references.bib`. |
| Produce experiments and results strong enough for workshop/conference review. | Final matched seven-method n=148 table exists and is packaged; failure taxonomy and qualitative examples exist; paired +2/+4, no-expand, no-rerank, verifier-repair, and answer-shape-repair ablations exist; compute/resource disclosure exists for the headline sweep. | Workshop-draft level. | Refresh compute disclosure if rerun, then tune to the selected venue's page budget. |
| Package artifacts so another reviewer can inspect them. | Slim review archive includes draft docs, PDF, headline tables, per-example rows, diagnostics, ablation summaries, ablation smoke runs, mechanism-ablation artifacts, qualitative assets, manifest checksums, source-PDF/asset release-risk audit, source-PDF terms manifest, and archive-readiness notes. A separate public-metadata package exists with no `.png`, `.jpg`, `.jpeg`, or `.pdf` files. | Achieved for current internal review handoff and safer public-metadata handoff; not yet final public-release complete. | Regenerate packages whenever paper docs or included artifacts change, then commit/tag or externally archive the chosen final package. |

## Current Completion Judgment

The goal is not yet complete. The workspace now contains a credible
submission-shaped paper package, but a conference/workshop submission still
needs at least:

1. target venue/workshop selection and official template conversion;
2. final checklist answers with stable section references and target-policy
   artifact/LLM-use disclosures;
3. final compute/resource disclosure matching the submitted result package;
4. final public/anonymized artifact release mode, including whether to use the
   current public-metadata package or a richer image package after per-source
   terms are cleared;
5. Zotero-backed bibliography reconciliation or an explicit non-Zotero
   primary-source bibliography waiver;
6. final venue-styled figures and captions;
7. an archived or committed code/doc snapshot matching the result package, with
   checksum sidecars and final SHA/DOI recorded.

## Safe Claim Boundary

Use the 61.5% FocusParse +4 matched table as the main paper result. The 66.9%
slide-deck/checkpoint result remains historical/provisional until raw
`run.json`, `per_example.jsonl`, code SHA, dataset revision, and materialization
logs are recovered or rerun.
