# FocusParse Paper Draft Package

Date: 2026-05-24

This directory is the working package for turning FocusParse into a
workshop/conference paper.

## Main Drafts

| File | Purpose |
| --- | --- |
| `focusparse-submission-draft.md` | Clean submission-facing paper draft with conservative claims, tables, figure slots, and citation keys. Start here when converting to LaTeX or a venue template. |
| `focusparse-paper-draft.md` | Longer research draft with more explanation, intermediate prose, and result discussion. Use as the source of detailed wording. |
| `latex/main.tex` | First standalone LaTeX draft with current abstract, sections, main result table, qualitative figures, and bibliography. |
| `latex/main.pdf` | Last compiled PDF from the standalone draft. |
| `references.bib` | Current primary-source bibliography. Zotero export is still blocked until Zotero Desktop/local API is available. |

## Supporting Audits

| File | Purpose |
| --- | --- |
| `artifact-provenance-audit.md` | Separates raw-verified results from documented-but-missing checkpoints. |
| `bibliography-readiness-audit.md` | Checks citation-key coverage, Zotero status, and bibliography gates. |
| `dataset-characterization.md` | Characterizes the canonical 148-row parser-bench paper slice. |
| `pinned-dataset-provenance.md` | Records the current HF revision, materialized benchmark SHA, and public repo pins for the final result package. |
| `pinned-headline-smoke-summary.md` | Records the successful seven-method smoke and rendered headline table against the pinned example-id file. |
| `pinned-smoke-run-summary.md` | Records the successful 3-row FocusParse smoke and the staging caveat it exposed. |
| `final-headline-run-summary.md` | Records the full matched seven-method n=148 paper run and artifact package. |
| `source-pdf-readiness.md` | Records source-PDF cache coverage for the pinned slice and the NFS archive fallback used for missing finance PDFs. |
| `source-pdf-and-asset-license-audit.md` | Release-risk audit for source PDFs, qualitative page/crop assets, and public artifact modes. |
| `source-pdf-terms-manifest.tsv` | One-row-per-PDF clearance checklist for source URLs, terms URLs, redistribution status, verification status, and notes. |
| `compute-resource-disclosure.md` | NeurIPS-style compute, provider, cost, latency, wall-clock, and local-host disclosure for the headline sweep. |
| `archival-snapshot-readiness.md` | Archive-mode, checksum-sidecar, git-state, and final release-gate checklist for paper package handoffs. |
| `smoke-example-ids.txt` | Stable smoke row IDs to use with `--example-ids-file` so shared staging stays 148 rows. |
| `methods-and-dataset-code-audit.md` | Maps method and dataset claims to the implementation and parser-bench code. |
| `experiments-results-audit.md` | Tracks experiment artifacts, result tiers, and rerun requirements. |
| `final-results-rerun-runbook.md` | Executable plan for regenerating the final seven-method paper result package. |
| `submission-review-package.md` | Records the slim review package generated from the current paper docs, headline table, per-example rows, ablation smoke runs, mechanism ablations, and qualitative assets. |
| `external-source-audit.md` | Records live Hugging Face, GitHub, arXiv, and Zotero source checks. |
| `venue-submission-plan.md` | Current venue timing, target order, and framing for NeurIPS/CVPR/ICLR/ICML/ACL-style submissions. |
| `venue-template-conversion-audit.md` | Maps the current draft/package into a NeurIPS-style venue template path and records the official template/checklist blockers. |
| `neurips-checklist-prep.md` | Draft NeurIPS-style checklist answers for claims, reproducibility, compute, assets, ethics, and LLM-use disclosure. |
| `related-work-failure-matrix.md` | Organizes related work by the failure mode FocusParse addresses. |
| `citation-map.md` | Explains why each citation appears and what claim it supports. |
| `qualitative-evidence-packets.md` | Prose-level qualitative example packet notes. |
| `qualitative-figure-manifest.md` | Figure asset readiness, local viewer paths, and crop/page provenance. |
| `qualitative-figure-panels.md` | Composed PNG panel paths and the commands that generated them. |
| `qualitative-baseline-comparisons.md` | Same-revision baseline predictions for the main qualitative examples. |
| `failure-taxonomy.md` | Final FocusParse +4 error-bucket counts from the May 24 `per_example.jsonl`. |
| `ablation-summary.md` | Current paired +2 versus +4 tool-set ablation generated from final run per-example rows. |
| `ablation-smoke-summary.md` | Three-row smoke checks for `--disable-expand-context`, `--disable-rerank`, and retry-off paper ablation switches. |
| `no-expand-ablation-summary.md` | Full n=148 no-expand mechanism ablation and paired flip analysis against final FocusParse +4. |
| `no-rerank-ablation-summary.md` | Full n=148 no-rerank mechanism ablation and paired flip analysis against final FocusParse +4. |
| `verifier-repair-ablation-summary.md` | Full n=148 verifier-directed repair ablation and paired flip analysis against final FocusParse +4. |
| `answer-shape-repair-ablation-summary.md` | Full n=148 answer-shape repair ablation and paired flip analysis against final FocusParse +4. |
| `submission-readiness-checklist.md` | Gate list for converting this package into a submit-ready paper. |
| `objective-completion-audit.md` | Requirement-by-requirement audit against the original paper goal. |
| `ablation-plan.md` | Concrete plan for the missing mechanism ablations reviewers are likely to ask for. |

## Current Claim State

Safe current headline:

- Raw-verified matched seven-method table:
  `results/hf/paper/2026-05-24-paper-headline-v1/`. FocusParse +4 reaches
  61.5% overall accuracy on 148 examples, with 66.3% datasheet accuracy,
  51.1% finance accuracy, page recall 0.914, BBox IoU 0.857, and
  $0.0248/correct.

Historical/provisional stronger checkpoint:

- 66.9% documented checkpoint, not yet raw-artifact verified in this checkout.
  Do not submit with this stronger number until `run.json`,
  `per_example.jsonl`, code SHA, dataset revision, and materialization logs are
  recovered or rerun.

Next artifact gate:

- The dataset pin is now materialized and recorded in
  `pinned-dataset-provenance.md`, and all 44 source PDFs are present locally as
  recorded in `source-pdf-readiness.md`. The pinned 3-row FocusParse smoke
  passed and is recorded in `pinned-smoke-run-summary.md`. The seven-method
  headline smoke also passed and is recorded in `pinned-headline-smoke-summary.md`.
  The full matched seven-method table, diagnostics, code/config snapshot, and
  artifact manifest have now been generated in
  `results/hf/paper/2026-05-24-paper-headline-v1/`, and the main draft files
  now reference that result. The final-run qualitative viewer bundle has also
  been generated at
  `results/agent_eyes/paper-final-headline-qualitative-focus-full/`. The first
  composed paper-panel PNGs are under
  `results/paper/qualitative-figure-panels/`, and same-revision qualitative
  baseline predictions are under
  `results/paper/qualitative-baseline-comparisons/`. A standalone LaTeX draft
  now compiles to `docs/research/paper-draft/latex/main.pdf`. A slim review
  package and archive have been generated under
  `results/paper/submission-review-package/`. A venue-template conversion
  audit now maps the current article-style source into the next official
  workshop/conference template, and `neurips-checklist-prep.md` now drafts the
  reproducibility/disclosure answers that should be ported into the selected
  venue checklist. `source-pdf-and-asset-license-audit.md` now records the
  public-release caveat for source PDFs and derived page/crop assets, and the
  package helper can now generate a `public-metadata` archive that excludes
  compiled PDFs and source-derived images. `source-pdf-terms-manifest.tsv`
  turns the 44-PDF clearance gate into a row-level checklist.
  `compute-resource-disclosure.md` now records the headline run's cost,
  latency, wall-clock, provider, and host disclosure.
  `archival-snapshot-readiness.md` records the current package modes and
  checksum-sidecar policy. Next gates are final venue-template styling and
  selecting the target venue/workshop.

## Current Venue Read

As of the 2026-05-24 official-source refresh, all named 2026 archival main
deadlines in the project goal have passed: CVPR, ACL, ICML, ICLR, and NeurIPS
main/Evaluations & Datasets. The best near-term route is a NeurIPS 2026
workshop submission after accepted workshops are announced on 2026-07-11, using
2026-08-29 as the central suggested workshop contribution date unless the
chosen workshop posts a different deadline. NeurIPS 2027 Evaluations & Datasets
/ main track remains the strongest full-paper target if the final result and
artifact package are ready.
