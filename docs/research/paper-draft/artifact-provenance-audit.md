# FocusParse Paper Artifact Provenance Audit

Date: 2026-05-24

Status: submission-prep audit for the current paper draft. This file separates
paper-safe evidence from documented but not locally reproducible claims.

## Claim Tiers

| Tier | Meaning | Paper use |
| --- | --- | --- |
| Raw artifact verified | Current worktree contains the exact `run.json` and `per_example.jsonl`, and row counts / metrics can be re-read from those files. | Safe for main tables once dataset revision and code SHA are pinned. |
| Documented but raw artifact missing | Research memo or changelog records the run, but the current worktree does not contain the corresponding raw result directory. | Mention only as a candidate / target until recovered or rerun. |
| Diagnostic / partial | Diagnostics, posthoc rescores, slices, smokes, or incomplete tables exist but do not prove a full benchmark result. | Use for ablation planning or qualitative discussion, not a headline claim. |

## Current Evidence Inventory

| Item | Current status | Evidence | Paper action |
| --- | --- | --- | --- |
| Public dataset surface | Verified current via Hugging Face connector. The dataset is `gabrielbo/parser-bench`, updated 2026-05-04, image+text parquet, `size_categories:n<1K`, 640 downloads at inspection time. External source details now live in `external-source-audit.md`. | `https://hf.co/datasets/gabrielbo/parser-bench` | Cite the dataset page, but report the pinned revision used for evaluation separately. |
| Pinned dataset materialization | Raw materialization verified locally. HF revision `3774c67f8b814392b6d04c939e904f749a3f52eb` materialized to 148 rows, 147 unique IDs, datasheet 101, finance 47, stress type `none`, benchmark SHA `e85b4df5032bc9e49fc74e1ed7492001794fbf4b46cc0f35d31a4cf32277962b`. | `results/hf/paper/2026-05-23-revision-pin/dataset/materialization-summary.json`; `docs/research/paper-draft/pinned-dataset-provenance.md` | Safe as dataset provenance for the final result rerun; not an accuracy result. |
| Source-PDF cache for pinned slice | Verified locally. All 44 source PDFs referenced by the pinned `benchmark.jsonl` are present under `/Users/gabrielbo/.cache/focusparse/pdfs`; 12 finance PDFs were pulled from NFS `archive/raw_pdfs/` after the default `raw/finance/` path failed. | `results/hf/paper/2026-05-23-revision-pin/dataset/source-pdf-readiness.json`; `docs/research/paper-draft/source-pdf-readiness.md` | Safe to use `--pdfs-root /Users/gabrielbo/.cache/focusparse/pdfs` for the final smoke/headline runs. |
| Pinned 3-row FocusParse smoke | Raw artifact verified locally. FocusParse +4 ran 3 pinned examples at 100% accuracy, total cost `$0.01872625`, lazy rate 0, with layout/model path successful and one Anthropic timeout recovered by retry. | `results/hf/paper/2026-05-23-revision-pin/smoke-focus-full/focusparse_focus_agentic_multi_page_0b139a04/run.json`; `docs/research/paper-draft/pinned-smoke-run-summary.md` | Safe as readiness evidence only; do not cite as a benchmark accuracy result. |
| Pinned seven-method headline smoke | Raw artifact verified locally. All seven method rows completed on the three pinned smoke IDs, produced rendered `headline_table` files, and diagnostics analyzed all seven specs. The shared staging stayed at 148 rows. | `results/hf/paper/2026-05-23-revision-pin/headline-smoke/headline_table.json`; `results/hf/paper/2026-05-23-revision-pin/headline-smoke/diagnostics/headline-smoke-diagnosis.md`; `docs/research/paper-draft/pinned-headline-smoke-summary.md` | Safe as orchestration/readiness evidence only; do not cite as a benchmark accuracy result. |
| Final matched seven-method paper run | Raw artifact verified locally. Full n=148 table completed for Base VLM, ReAct +2/+4, Agent baseline +2/+4, and FocusParse +2/+4 against the pinned HF revision and PDF root. FocusParse +4 is 61.5% overall, 66.3% datasheet, 51.1% finance; every method has 148 per-example rows. | `results/hf/paper/2026-05-24-paper-headline-v1/headline/headline_table.json`; `results/hf/paper/2026-05-24-paper-headline-v1/manifest.json`; `docs/research/paper-draft/final-headline-run-summary.md` | Safe as the current main result table once the gitignored result directory is archived/committed. |
| Canonical paper slice | Code path verified. `src/focusparse/eval/hf_loader.py` defaults to HF `validation` and filters rows with `_filter_stress_rows()`, keeping `stress_type in (None, "", "none")`. | `src/focusparse/eval/hf_loader.py` | Paper must report exact revision, stress filter, and final row count. |
| Seven-row all-method table in the draft | Documented in `docs/research/2026-05-12-scientific-recalibration-and-experiment-plan.md`, but its cited raw directory `results/hf/headline-v1-rebaseline-v2/` is absent in the current worktree. `results/diagnostics/rebaseline-v2/report.md` exists and supports the relative story on 147 rows, while `results/hf/headline-v1/headline_table.json` is a present 148-row table with different values. | `docs/research/2026-05-12-scientific-recalibration-and-experiment-plan.md`, `results/diagnostics/rebaseline-v2/report.md`, `results/hf/headline-v1/headline_table.json` | Keep the table conservative and mark it as research-doc recorded until a final paper table is regenerated from raw artifacts. |
| Merged 60.14% FocusParse checkpoint | Raw artifact verified locally, older checkpoint. `run.json` reports 148 rows, accuracy 0.601351, datasheet 64/101, finance 25/47, cost/correct `$0.0243`, latency 4.26s, page recall 0.892, BBox IoU 0.870, lazy rate 0.041. `per_example.jsonl` has 148 rows. | `results/hf/sprint-2026-05-15/answer-shape-normalizer-oai-run2/focusparse_focus_agentic_multi_page_8c5e328d/run.json` | Historical FocusParse evidence; superseded for headline use by the final matched seven-method paper run. |
| Candidate 66.9% FocusParse checkpoint | Documented but raw artifact missing locally. `docs/research/2026-05-15-harness-65plus-post-evidence-iteration.md` and `.claude/memory/project_changelog.md` record `shape-normalizer-full-run1` at 99/148 = 66.9%, but `find results ... shape-normalizer-full-run1` found no current raw result path. | `docs/research/2026-05-15-harness-65plus-post-evidence-iteration.md`, `.claude/memory/project_changelog.md` | Do not use as final headline until recovered or rerun with raw artifacts. |
| Inspect / expand mechanism | Code contract verified. `EvidencePacket` is the reasoner boundary and carries crop refs, linked neighbors, OCR/text, chart CSV, provenance, and confidence. `inspect_region` has exactly `image`, `element`, and `region` modes. `expand_context` attaches role-labeled neighbors. | `src/focusparse/evidence/packet.py`, `src/focusparse/tools/inspect_region.py`, `src/focusparse/pipeline/expander.py` | Safe to explain in Methods as the core harness mechanism. |
| Zotero bibliography pass | Blocked by local app state. Helper runs, but `127.0.0.1:23119` refuses connections, no Zotero profile/prefs are visible, and `open -a Zotero` reports no Zotero app. | `python3 .../zotero.py status --json`; `open -a Zotero` | Keep primary-source bibliography for now; export from Zotero once the app/profile is available. |

## Commands Used For This Audit

```bash
find results/hf -maxdepth 2 -type d -name '*rebaseline*' -o -name '*headline*' -o -name '*shape*' -o -name '*chart-period*'
find results -path '*shape-normalizer-full-run1*' -o -path '*shape-normalizer-target-control-run1*' -o -path '*chart-period-full-run2*'
jq '{n_examples, aggregate, aggregate_by_domain, tool_set, available_tools, focus_features, env_snapshot}' \
  results/hf/sprint-2026-05-15/answer-shape-normalizer-oai-run2/focusparse_focus_agentic_multi_page_8c5e328d/run.json
wc -l \
  results/hf/sprint-2026-05-15/answer-shape-normalizer-oai-run2/focusparse_focus_agentic_multi_page_8c5e328d/per_example.jsonl
```

## Submission Gates

The paper can now use the 61.5% final matched result as the main headline.
Before the paper can treat the older `66.9%` checkpoint as the headline result,
recover or rerun:

1. `shape-normalizer-full-run1/run.json`
2. `shape-normalizer-full-run1/per_example.jsonl`
3. the exact code commit SHA
4. the exact HF dataset revision
5. materialization logs showing 148 post-filter examples
6. method/table export via:

```bash
uv run python scripts/render_headline_table.py <path-to-headline_table.json>
```

If recovery fails, the paper should use the final matched 61.5% result as the
main current FocusParse checkpoint and present 66.9% only as a documented but
not yet paper-safe follow-up target.
