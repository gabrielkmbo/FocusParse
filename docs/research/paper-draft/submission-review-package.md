# FocusParse Submission Review Package

Date: 2026-05-26

Status: generated slim artifact package for reviewing the current paper draft,
final matched headline table, 3-row ablation smoke checks, and the n=148
no-expand/no-rerank/verifier-repair/answer-shape-repair mechanism ablations
without copying the full 4.3 GB headline payload, the 627M no-expand tile
directory, the 633M no-rerank tile directory, or the 631M verifier-repair tile
directory.

## Package Paths

Directory:

```text
results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32/
```

Archive:

```text
results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32.tar.gz
```

Size check:

```text
directory: 116M
archive: 46M
```

The generated `manifest.json` has 262 checksum-tracked files. The archive has
313 tar members including directories. The helper also writes:

```text
results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32.tar.gz.sha256
```

## Generation Command

```bash
uv run python scripts/package_paper_review_artifacts.py
```

The helper refuses to overwrite an existing package or archive. Use a new
`--package-name` for another dated snapshot.

## Public-Metadata Package

For public or double-blind artifact planning, the helper can build a
source-safer package that excludes compiled PDFs and source-derived page,
crop, tile, and figure-panel images:

```bash
uv run python scripts/package_paper_review_artifacts.py --release-mode public-metadata
```

Current public-metadata output:

```text
results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10/
results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10.tar.gz
```

Size check:

```text
directory: 75M
archive: 8.8M
```

The public-metadata `manifest.json` has 106 checksum-tracked files. The archive
has 150 tar members including directories, and validation found no `.png`,
`.jpg`, `.jpeg`, or `.pdf` files. The helper also writes:

```text
results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10.tar.gz.sha256
```

## Included

- paper draft sources, `references.bib`, and `latex/main.pdf`;
- objective-completion and ablation planning audits;
- venue-template conversion audit for the next official author kit;
- NeurIPS-style checklist prep for claims, reproducibility, compute, assets,
  ethics, and LLM-use disclosure;
- compute/resource disclosure for the headline sweep;
- archival snapshot readiness notes and checksum-sidecar policy;
- source-PDF and derived-image release-risk audit;
- source-PDF terms manifest with one row per pinned source PDF;
- citation map and related-work failure matrix;
- paired +2 versus +4 ablation summary artifacts;
- 3-row no-expand, no-rerank, and retry-off ablation smoke artifacts;
- n=148 no-expand, no-rerank, verifier-repair, and answer-shape-repair
  mechanism ablation summaries and light run artifacts;
- final headline tables and method-summary JSON files from
  `results/hf/paper/2026-05-24-paper-headline-v1/`;
- every method's `run.json` and `per_example.jsonl`;
- final result `manifest.json`, config snapshot, git snapshot, and diagnostics;
- generated failure-taxonomy Markdown, CSV, and JSON;
- composed qualitative figure panels;
- same-revision qualitative baseline comparison table;
- lighter trace-viewer crop/page asset bundle for the four qualitative
  examples;
- agent-eyes viewer index plus `agent_eyes_audit.jsonl`.

## Excluded

- full `tiles/`, `predictions/`, `text_layer/`, and `crops/` payloads from the
  4.3 GB headline result directory;
- full agent-eyes example HTML files, which remain in
  `results/agent_eyes/paper-final-headline-qualitative-focus-full/examples/`.

To include the heavy agent-eyes examples in a future snapshot, run the helper
with `--include-agent-eyes-examples` and a new `--package-name`.

## Validation

The package was checked for:

- `paper-docs/latex/main.pdf`;
- `paper-docs/ablation-smoke-summary.md`;
- `paper-docs/no-expand-ablation-summary.md`;
- `paper-docs/no-rerank-ablation-summary.md`;
- `paper-docs/verifier-repair-ablation-summary.md`;
- `paper-docs/answer-shape-repair-ablation-summary.md`;
- `paper-docs/citation-map.md`;
- `paper-docs/related-work-failure-matrix.md`;
- `paper-docs/venue-template-conversion-audit.md`;
- `paper-docs/neurips-checklist-prep.md`;
- `paper-docs/compute-resource-disclosure.md`;
- `paper-docs/archival-snapshot-readiness.md`;
- `paper-docs/source-pdf-and-asset-license-audit.md`;
- `paper-docs/source-pdf-terms-manifest.tsv`;
- `analysis/mechanism-ablation/no-expand-v1/focusparse-no-expand-ablation.md`;
- `analysis/mechanism-ablation/no-rerank-v1/focusparse-no-rerank-ablation.md`;
- `analysis/mechanism-ablation/verifier-off-v1/focusparse-verifier-repair-ablation.md`;
- `analysis/mechanism-ablation/answer-shape-off-v1/focusparse-answer-shape-repair-ablation.md`;
- `results/mechanism-ablation/no-expand/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl`;
- `results/mechanism-ablation/no-rerank/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl`;
- `results/mechanism-ablation/verifier-off/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl`;
- `results/mechanism-ablation/answer-shape-off/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl`;
- `analysis/ablation-smoke/no-expand/focusparse_focus_agentic_multi_page_0b139a04/run.json`;
- `analysis/failure-taxonomy/failure-taxonomy.md`;
- `results/headline/headline/headline_table.json`;
- FocusParse +4 `per_example.jsonl`;
- Latvia qualitative panel PNG;
- trace-viewer asset index.

No required files were missing in the validation pass.

## Public-Metadata Validation

The public-metadata package was checked for:

- `paper-docs/source-pdf-and-asset-license-audit.md`;
- `paper-docs/neurips-checklist-prep.md`;
- `paper-docs/venue-template-conversion-audit.md`;
- `paper-docs/compute-resource-disclosure.md`;
- `paper-docs/archival-snapshot-readiness.md`;
- `paper-docs/source-pdf-terms-manifest.tsv`;
- `paper-docs/references.bib`;
- `paper-docs/citation-map.md`;
- `paper-docs/related-work-failure-matrix.md`;
- `paper-docs/answer-shape-repair-ablation-summary.md`;
- `results/headline/headline/headline_table.json`;
- FocusParse +4 `per_example.jsonl`;
- zero `.png`, `.jpg`, `.jpeg`, or `.pdf` files.
