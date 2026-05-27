# FocusParse Venue Template Conversion Audit

Date: 2026-05-24

Status: conversion plan for turning the current paper package into a
submission-ready workshop or conference template. This is not the final venue
source file yet because the near-term workshop target is not selected until
NeurIPS 2026 accepted workshops are announced.

## Current Target

Primary near-term path:

```text
NeurIPS 2026 workshop paper
```

Reason:

- The named 2026 archival main-track deadlines in the original goal have
  passed for NeurIPS, ICLR, ICML, ACL, and CVPR-style main submissions.
- NeurIPS 2026 workshop accepted-workshop notification is scheduled for
  2026-07-11 AoE.
- The suggested submission date for workshop contributions is 2026-08-29 AoE,
  with mandatory workshop accept/reject notification by 2026-09-29 AoE.
- Individual workshops may set different paper lengths, archival status,
  anonymity rules, and supplementary-material policies, so the final template
  must be chosen after the target workshop call is posted.

Secondary archival path:

```text
NeurIPS 2027 Evaluations & Datasets or main track
```

Reason:

- The paper is naturally an evaluation/method artifact: dataset, harness,
  result table, ablations, failure taxonomy, qualitative traces, and
  reproducibility package.
- NeurIPS 2026 main/Evaluations & Datasets are closed, but their checklist,
  artifact, and ethics requirements are the best preparation target.

## Official Source Facts To Preserve

Source URLs checked on 2026-05-24:

```text
https://neurips.cc/Conferences/2026/CallForPapers
https://neurips.cc/Conferences/2026/MainTrackHandbook
https://neurips.cc/Conferences/2026/WorkshopsGuidance
```

Current source facts:

| Item | Requirement / fact | FocusParse implication |
| --- | --- | --- |
| NeurIPS 2026 main dates | Abstract deadline 2026-05-04 AoE; full paper deadline 2026-05-06 AoE. | Main 2026 submission is closed; do not frame the package as a current main-track submission. |
| NeurIPS 2026 workshop timing | Accepted workshops announced 2026-07-11 AoE; suggested workshop contribution date 2026-08-29 AoE; mandatory notification 2026-09-29 AoE. | Prepare a workshop-length version now, then bind it to a specific accepted workshop later. |
| Main-track formatting | Single PDF: main content, references, appendices, checklist. Main text limited to 9 content pages including figures/tables; references, appendices, and checklist do not count; max PDF size 50MB. | Current standalone LaTeX draft is 7 pages, so it is under the main-track content budget, but it still uses an article template rather than the official style. |
| Style file | Submissions must use the current-year LaTeX style file; NeurIPS says this is the only accepted template and style violations can cause desk rejection. | Final source must be converted from `latex/main.tex` into the official author kit once the target venue/workshop is selected. |
| Checklist | NeurIPS requires a paper checklist in the submitted PDF. | Create checklist answers from the current result package before final submission. |
| Workshop archival status | NeurIPS workshop papers are non-archival by default; organizers decide whether/how to expose accepted papers. | Use workshop submission to get feedback; preserve the stronger archival path for a later main/E&D submission. |

## Current Source To Convert

Primary source files:

```text
docs/research/paper-draft/focusparse-submission-draft.md
docs/research/paper-draft/latex/main.tex
docs/research/paper-draft/references.bib
```

Current compiled PDF:

```text
docs/research/paper-draft/latex/main.pdf
```

Current review package:

```text
results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32.tar.gz
results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32.tar.gz.sha256
```

Current status:

- `latex/main.tex` compiles to a 7-page standalone article-style PDF.
- It already contains the conservative 61.5% headline, main result table,
  mechanism ablation table, qualitative figure panels, limitations, and
  bibliography.
- It is not yet the official NeurIPS template and does not include the
  mandatory checklist.
- `neurips-checklist-prep.md` now contains draft checklist answers and evidence
  paths to port once the official venue source exists.

## Section Mapping

| Current section | Venue-template destination | Action |
| --- | --- | --- |
| Abstract | `abstract` environment | Keep conservative 61.5% claim; do not mention the raw-missing 66.9% checkpoint in the abstract. |
| Introduction | Main body page 1 | Tighten to one page if workshop has a 4-page or 6-page limit. |
| Related Work | Main body | Keep failure-mode structure; preserve the `ParseBench` versus `parser-bench` distinction. |
| Parser-Bench Dataset | Methods / Dataset section | Keep table with 148-row paper slice and public-HF-versus-pinned-slice caveat. |
| FocusParse Method | Methods section | Add a compact pipeline schematic or use one figure slot if the target workshop allows it. |
| Experiments | Experiments section | Keep seven-method main table and state HF revision / result package path in reproducibility note. |
| Mechanism Ablations | Results / Analysis section | Keep four-row table: no-rerank, no-expand, repair-off, answer-shape-off. |
| Failure Taxonomy | Analysis or appendix | Main text if page budget permits; otherwise appendix. |
| Qualitative Analysis | Figure section | Keep Latvia and JESD204B figures as the two main evidence-packet examples. |
| Limitations | Limitations / checklist | Keep raw-missing 66.9% caveat, small slice caveat, Zotero caveat, and answer-shape negative-control caveat. |
| Bibliography | References | Keep primary-source BibTeX; rerun Zotero once available. |

## Figure And Table Budget

Recommended workshop version:

| Asset | Keep in main body? | Reason |
| --- | --- | --- |
| Main result table | Yes | Core evidence that FocusParse beats no-tool and generic-agent baselines. |
| Mechanism ablation table | Yes | Core evidence for inspect/expand/localization thesis. |
| Dataset table | Yes, compact | Needed to explain parser-bench paper slice. |
| Latvia qualitative panel | Yes | Best finance cross-region evidence-binding example. |
| JESD204B qualitative panel | Yes if page budget allows; otherwise appendix | Best datasheet cross-page compaction example. |
| Failure taxonomy table | Appendix if short paper | Important analysis, but less central than main result + ablation tables. |
| Source/provenance table | Appendix or supplement | Preserve reproducibility without crowding main text. |

## Checklist Draft Answers To Prepare

These are not final checklist answers, but they identify what the venue
conversion must cover.

| Checklist area | Current answer direction | Evidence source |
| --- | --- | --- |
| Limitations | Yes. Small 148-row slice, finance n=47, raw-missing 66.9% checkpoint, current answer-shape repair negative control, and article-style template caveat. | `focusparse-submission-draft.md`, `objective-completion-audit.md` |
| Reproducibility | Yes. The package contains run JSON, per-example rows, config snapshot, manifest, diagnostics, and runbook. | `submission-review-package.md`, `final-results-rerun-runbook.md` |
| Dataset documentation | Yes, but final submission should cite public HF dataset plus pinned paper revision and source-PDF readiness. | `dataset-characterization.md`, `pinned-dataset-provenance.md`, `source-pdf-readiness.md` |
| Compute/resources | Yes for the headline sweep. The compute disclosure records provider/model roles, local host, parallelism, wall-clock envelope, reported model-call cost, and exclusions. | `compute-resource-disclosure.md`, `final-headline-run-summary.md`, method `run.json` files |
| Ethics / risks | Low direct human-subject risk; still discuss finance-document QA reliability, hallucinated citations, and non-production sandbox status. | `submission-readiness-checklist.md`, AGENTS.md threat-model notes |
| AI/LLM use | Needs final policy answer. The draft and code were produced with Codex assistance; final disclosure depends on target venue/workshop policy. | This audit plus final submission policy |
| Code/data availability | Available as repo/dataset references, but double-blind and archive decisions remain. | `external-source-audit.md`, `artifact-provenance-audit.md` |

## Concrete Conversion Steps

When the target workshop or archival venue is selected:

1. Download the official current-year author kit from the venue call.
2. Create a new source directory, for example:

```text
docs/research/paper-draft/latex/neurips-workshop/
```

3. Copy the official style files into that directory without modifying them.
4. Port the body of `docs/research/paper-draft/latex/main.tex` into the
   official shell file.
5. Add the mandatory checklist file or checklist section required by the venue.
6. Port draft answers from `neurips-checklist-prep.md` and add stable
   section/page references after the venue PDF compiles.
7. Switch authors to anonymous placeholders for review unless the target
   workshop explicitly uses non-anonymous submissions.
8. Compile and check:

```bash
python3 /Users/gabrielbo/.codex/plugins/cache/openai-bundled/latex/0.2.0/scripts/compile_latex.py \
  /Users/gabrielbo/projects/FocusParse/docs/research/paper-draft/latex/neurips-workshop/main.tex \
  --json
```

9. Check final PDF page count and file size against the target call.
10. Regenerate the slim review package so it contains the venue source, PDF, and
   checklist.
11. Update `submission-readiness-checklist.md`, `neurips-checklist-prep.md`,
    `compute-resource-disclosure.md`, and this audit with the selected
    venue, template source URL, page limit, anonymity policy, and final compile
    result.

## Current Blockers

| Blocker | Status | What unblocks it |
| --- | --- | --- |
| Target workshop not selected | Expected; accepted NeurIPS workshops are not announced until 2026-07-11. | Pick a workshop after accepted list and call pages are posted. |
| Official workshop-specific template unknown | Expected; workshops may set their own format/length. | Use selected workshop CFP. |
| Zotero export unavailable | Blocked by local Zotero app/API state. | Install/start Zotero Desktop with local API on `127.0.0.1:23119`, then export/check BibTeX. |
| Artifact archive/DOI not finalized | Open. | Commit/push or archive code/docs/results; decide double-blind artifact handling. |

## Submission-Ready Definition

This gate should be considered complete only when all of the following are
true:

- selected target venue/workshop is named;
- target call URL and template URL are recorded;
- official style file is present in a venue-specific source directory;
- venue-specific PDF compiles;
- page count and file size meet the target call;
- checklist is completed if required;
- checklist answers include stable references and artifact/LLM-use disclosures
  consistent with target policy;
- bibliography has either a Zotero-backed export or an explicit primary-source
  bibliography waiver;
- slim review package contains the venue source, final PDF, checklist, result
  artifacts, and manifest.
