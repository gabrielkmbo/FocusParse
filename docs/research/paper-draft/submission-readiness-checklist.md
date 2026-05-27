# FocusParse Paper Submission Readiness Checklist

Date: 2026-05-26

Status: working checklist for turning the current Markdown draft into a
workshop/conference submission.

## Claim To Prove

Primary claim:

> On concentrated high-resolution finance and datasheet documents, performance
> depends on constructing compact, localized evidence before reasoning. The
> useful unit is not a whole page or an isolated crop, but an evidence packet
> that binds a readable region to captions, legends, headers, footnotes, axes,
> and cross-page references.

Submission-safe version today:

> On the pinned 148-row parser-bench paper slice, the final matched table shows
> FocusParse +4 at 61.5% overall accuracy, 66.3% on datasheets, and 51.1% on
> finance, outperforming Base VLM (43.9%) and generic tool-agent comparators
> (6.1%-18.2%) under the same protocol.

Candidate stronger version after artifact recovery/rerun:

> A separate documented 66.9% FocusParse checkpoint may become a stronger
> headline only if its raw artifacts are recovered or rerun. Until then, it is a
> historical/provisional checkpoint, not the paper headline.

## Required Main Tables

| Table | Purpose | Current status | Gate |
| --- | --- | --- | --- |
| Dataset table | Define parser-bench paper slice: n, domains, families, multi-region rows, evidence spread, answer types. | Characterized from a pinned HF revision and local 148-row materialization. | Revalidate from the final result directory before submission. |
| Main result table | Compare Base VLM, ReAct +2/+4, Agent +2/+4, FocusParse +2/+4. | Final matched n=148 table exists at `results/hf/paper/2026-05-24-paper-headline-v1/headline/headline_table.json`; the paper drafts and slim review package now reference it. | Commit or externally archive the exact code/docs before submission. |
| FocusParse checkpoint table | Show raw-verified current result and historical 66.9% candidate. | Final matched FocusParse +4 is 61.5%; historical 66.9% remains documented but raw-missing. | Use 61.5% as the submission-safe headline unless 66.9% is recovered/rerun. |
| External source table | Distinguish Gabriel `parser-bench` from external RunLlama `ParseBench`, plus current public repo/dataset links. | `external-source-audit.md` drafted from live HF/GitHub/arXiv checks and now includes public repo/HF pins. | Replace moving URLs with archive DOIs where needed. |
| Mechanism table | Accuracy, BBox IoU, page recall, lazy rate, cost/correct. | Drafted from the final same-code matched run. | Final venue-template styling. |
| Ablation table | Inspect only, inspect+expand, no rerank, no verifier repair, answer-shape off/on. | Coarse +2 versus +4 paired ablation exists in `ablation-summary.md`; full n=148 no-expand, no-rerank, verifier-directed repair, and answer-shape repair ablations exist in `no-expand-ablation-summary.md`, `no-rerank-ablation-summary.md`, `verifier-repair-ablation-summary.md`, and `answer-shape-repair-ablation-summary.md`. | Final venue-template styling. |

## Required Paper Source

| Artifact | Purpose | Current status | Gate |
| --- | --- | --- | --- |
| Submission-facing draft | Clean paper source that can be converted to LaTeX or a venue template. | Markdown draft exists, and `docs/research/paper-draft/latex/main.tex` now compiles to `main.pdf` with the final table and draft qualitative figures. `venue-template-conversion-audit.md` maps the current source into the next official template. | Convert to the selected venue template after target venue/workshop selection. |
| Bibliography | Venue-ready BibTeX. | `references.bib` exists from primary sources and all current draft citekeys resolve. Zotero Desktop is not currently available on this profile. | Re-export/check with Zotero once the app/local API is available. |
| Venue plan | Target venue, framing, and deadline reality. | `docs/research/paper-draft/venue-submission-plan.md` was refreshed against official pages on 2026-05-24. | Re-check dates before committing to a specific workshop/conference. |
| Venue-template conversion audit | Official template, checklist, page-budget, and source-mapping plan. | `docs/research/paper-draft/venue-template-conversion-audit.md` records the NeurIPS-style conversion path and current blockers. | Replace the article-style draft with the selected workshop/conference author kit once the target call is known. |
| Checklist prep | Draft reproducibility, compute, asset, ethics, and LLM-use answers for a NeurIPS-style checklist. | `docs/research/paper-draft/neurips-checklist-prep.md` maps the current artifacts to the official checklist areas. | Port into the selected venue checklist and add stable section/page references. |
| Compute/resource disclosure | Run envelope, model providers, local host, cost, and latency disclosure for the headline sweep. | `docs/research/paper-draft/compute-resource-disclosure.md` records the seven-method sweep: 1,036 example-runs, 2.56h wall-clock envelope, 4.54 summed method-hours, and $16.9441 reported model-call cost. | Refresh if the final table is rerun, provider pricing changes, or execution moves to another host. |
| Archival snapshot readiness | Package modes, checksum sidecars, git state, and final archive gate. | `docs/research/paper-draft/archival-snapshot-readiness.md` records the internal/public package targets and explains the `.tar.gz.sha256` sidecars. | Commit/tag or externally archive the exact final code/docs/results and record the final SHA/DOI. |
| Final rerun runbook | Executable command sequence and artifact layout for the final paper result package. | `docs/research/paper-draft/final-results-rerun-runbook.md` exists. | Execute it and update this checklist from the resulting package. |
| Pinned smoke | Validate credentials, layout endpoint, source-PDF path, and FocusParse +4 write path before full headline spend. | `pinned-smoke-run-summary.md` records a successful 3-row smoke. | Use `--example-ids-file`, not `--limit`, for any future smoke sharing the final staging root. |
| Headline smoke | Validate all seven method wrappers, headline merge, renderer, and diagnostics before the full sweep. | `pinned-headline-smoke-summary.md` records a successful seven-method smoke with one row per configured method spec. | Run the full n=148 sweep against the same pin and PDF root. |
| Final headline package | Raw table, diagnostics, config/git snapshot, and result manifest for the paper claim. | `final-headline-run-summary.md` records the completed package at `results/hf/paper/2026-05-24-paper-headline-v1/`; a slim review archive now exists under `results/paper/submission-review-package/`. | Commit or externally archive the exact code/docs before submission. |
| Source-PDF and asset license audit | Public-release posture for source PDFs, page renders, crops, tiles, and paper panels. | `source-pdf-and-asset-license-audit.md` records current known licenses and release-risk buckets; `source-pdf-terms-manifest.tsv` now has one row per pinned source PDF with no remaining `TODO` source/terms fields: 42 official web-verified rows, one Nordic official-PDF/no-reproduction row, and one TTP223B distributor-mirror row where no official manufacturer source was found; `scripts/package_paper_review_artifacts.py --release-mode public-metadata` builds a source-safer package with no image/PDF files. | Resolve the TTP223B non-official-source caveat if an original manufacturer URL or permission contact becomes available, and decide whether any public artifact may include derived page/crop assets. |

## Required Figures

| Figure | Purpose | Current status | Gate |
| --- | --- | --- | --- |
| Pipeline schematic | Show `plan -> route -> localize -> rerank -> inspect -> expand -> answer -> verify`. | Described in text. | Render clean conference figure. |
| Evidence packet diagram | Show tight crop plus caption/legend/header/footnote neighbors. | Described in Methods. | Use one real trace packet. |
| Latvia finance qualitative | Demonstrate cross-region chart/table/footnote binding. | Final-run viewer, draft PNG panel, and same-revision baseline table generated. | Final venue-template styling and decide whether comparator answers appear in figure body, caption, or appendix. |
| JESD204B datasheet qualitative | Demonstrate cross-page timing evidence compaction. | Final-run viewer, draft PNG panel, and same-revision baseline table generated. | Final venue-template styling and decide whether comparator answers appear in figure body, caption, or appendix. |
| Infineon Q1/Q2 near-miss | Demonstrate honest answer/localization split. | Final-run viewer generated; final BBox IoU is 0.256. | Use as appendix/analysis with the low-IoU interpretation preserved. |
| ADRV9040 compaction near-miss | Demonstrate an answer-shape/field-preservation failure. | Final-run viewer generated, but the prediction omits `641 kb` despite scorer credit. | Use only as analysis or replace with a rerun that preserves both requested fields. |
| Failure taxonomy | Show localization vs extraction vs answer-shape failures. | Generated from the final FocusParse +4 `per_example.jsonl` under `results/paper/failure-taxonomy/` and summarized in `failure-taxonomy.md`. | Decide whether the table belongs in the main analysis or appendix after venue page budget is known. |

## Required Provenance Package

The submission result directory should contain:

- final `headline_table.json`;
- rendered `headline_table.md` / `.csv`;
- every method's `run.json`;
- every method's `per_example.jsonl`;
- dataset materialization manifest with HF repo, split, revision, row count, and
  stress-filter count;
- source-PDF readiness manifest showing every pinned-slice PDF is present under
  the `--pdfs-root` path used by final runs;
- code commit SHA;
- config snapshot;
- qualitative figure source rows and crop/page assets, including the final-run
  viewer at `results/agent_eyes/paper-final-headline-qualitative-focus-full/`,
  draft panel PNGs at `results/paper/qualitative-figure-panels/`, and
  same-revision baseline comparisons at
  `results/paper/qualitative-baseline-comparisons/`;
- `docs/research/paper-draft/qualitative-figure-manifest.md` updated with any
  regenerated crop bundle paths;
- `docs/research/paper-draft/external-source-audit.md` updated with final pinned
  external URLs, revisions, or archive DOIs;
- `docs/research/paper-draft/source-pdf-and-asset-license-audit.md` updated
  with final per-PDF source URLs, terms, redistribution status, and release
  mode for derived images;
- `docs/research/paper-draft/source-pdf-terms-manifest.tsv` completed with
  official source URLs, terms URLs, access dates, and redistribution status for
  all 44 pinned source PDFs; it currently has no remaining `TODO` source/terms
  fields, with 42 official web-verified rows, one Nordic
  official-PDF/no-reproduction row, and one TTP223B distributor-mirror row where
  no official manufacturer source was found;
- `docs/research/paper-draft/venue-submission-plan.md` refreshed against the
  actual target venue call;
- `docs/research/paper-draft/venue-template-conversion-audit.md` updated with
  the target author kit, page limit, checklist policy, and final compile
  result;
- `docs/research/paper-draft/neurips-checklist-prep.md` updated with final
  checklist answers, stable section/page references, artifact URL policy,
  compute statement, and license/asset audit status;
- `docs/research/paper-draft/compute-resource-disclosure.md` updated with the
  final result package, provider price table date, local/remote host, wall-clock
  envelope, and total reported model-call cost;
- `docs/research/paper-draft/archival-snapshot-readiness.md` updated with the
  final package names, checksum sidecars, git commit/tag or archive DOI, and
  selected release mode;
- `docs/research/paper-draft/objective-completion-audit.md` updated with the
  current status of every user-requested paper requirement;
- `docs/research/paper-draft/ablation-plan.md` updated or superseded by actual
  ablation results;
- `docs/research/paper-draft/ablation-summary.md` updated when paired ablation
  artifacts are regenerated;
- diagnostic report from `scripts/diagnose_predictions.py`;
- short README explaining how to rerun the exact table.

Follow `docs/research/paper-draft/final-results-rerun-runbook.md` for the
current command sequence and expected result directory layout. For review
handoffs, the slim package recorded in
`docs/research/paper-draft/submission-review-package.md` includes the paper PDF,
headline tables, all method `run.json` / `per_example.jsonl` files, diagnostics,
figures, and checksums without copying the full 4.3 GB raw payload.

## Open External-Tool Items

- Zotero: blocked until Zotero Desktop is installed or available on this
  machine/profile and exposes the API on `127.0.0.1:23119`; the current helper
  status returns connection refused and `open -a Zotero` cannot find the app.
- Hugging Face: verified as `gabrielbo/parser-bench` and pinned at revision
  `3774c67f8b814392b6d04c939e904f749a3f52eb`; the same pin is recorded in the
  full result manifest at
  `results/hf/paper/2026-05-24-paper-headline-v1/manifest.json`.
- Source PDFs: all 44 pinned-slice source PDFs are present locally under
  `/Users/gabrielbo/.cache/focusparse/pdfs`; keep this cache or rerun
  `scripts/source_pdfs_from_nfs.py` before final evaluations.
- GitHub: repository identities verified; current public pins are FocusParse
  `1af7f2f413a7a228deb5644ddca67888d367a8f5` and parse-bench
  `7685c36526b26bf3326a776c11f14354d506ebaa`. Final paper should use commits
  or archive DOIs rather than moving branches.

## Stop Conditions Before Submission

Do not submit until:

1. The main table from `results/hf/paper/2026-05-24-paper-headline-v1/` is
   reflected in the abstract, Results, and conclusion.
2. Every headline number has a raw artifact path.
3. The abstract and conclusion use the same claim strength as the verified
   result tier.
4. The related work distinguishes `parser-bench` from external ParseBench.
5. The qualitative examples have real figure assets and final venue-template
   panels, not only prose or draft boards.
6. `focusparse-submission-draft.md` has been updated from the final result
   package and no longer mixes historical checkpoints into the main claim.
7. The standalone LaTeX draft has been converted into the target venue's
   current template.
8. The target venue/workshop has been selected and its current template,
   anonymity, archival, and supplementary-material rules have been checked.
9. Final checklist answers have been filled from `neurips-checklist-prep.md`
   with stable section references and target-policy-compliant artifact/LLM-use
   disclosures.
10. `compute-resource-disclosure.md` matches the final submitted result package.
11. `archival-snapshot-readiness.md` records the exact submitted package,
    checksum sidecar, and clean commit/tag or archive DOI.
12. Public or anonymous artifact release mode has been selected from
    `source-pdf-and-asset-license-audit.md`; the current safe default is the
    `public-metadata` package, and any uncleared source PDFs or derived
    page/crop/tile assets are excluded.
13. The final-result directory follows the runbook package layout and contains
   no mixed-revision or mixed-code rows.

## Current Target Read

As of the 2026-05-24 official-source refresh, all named 2026 archival main
deadlines in the original goal have passed: CVPR, ACL, ICML, ICLR, and NeurIPS
main/Evaluations & Datasets. The live practical target is a NeurIPS 2026
workshop paper after accepted workshops are announced on 2026-07-11, with
2026-08-29 as the central suggested contribution date unless a chosen workshop
sets a different official deadline. NeurIPS 2027 Evaluations & Datasets remains
the strongest full-paper target.
