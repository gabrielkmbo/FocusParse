# FocusParse Archival Snapshot Readiness

Date: 2026-05-26

Status: archive-readiness manifest for the current paper package. This file
records the artifacts that can be handed off now and the remaining steps before
the package should be treated as a final public or submission archive.

## Snapshot Summary

| Item | Value |
| --- | --- |
| Code `HEAD` at inspection time | `1af7f2f413a7a228deb5644ddca67888d367a8f5` |
| Worktree state | Dirty; paper docs, scripts, generated outputs, and several eval/harness files are modified or untracked. |
| Main result root | `results/hf/paper/2026-05-24-paper-headline-v1/` |
| Result root run slug | `2026-05-24-paper-headline-v1` |
| HF dataset revision | `3774c67f8b814392b6d04c939e904f749a3f52eb` |
| Benchmark JSONL SHA-256 | `e85b4df5032bc9e49fc74e1ed7492001794fbf4b46cc0f35d31a4cf32277962b` |
| Current internal package target | `focusparse-paper-review-package-2026-05-24-v32` |
| Current public-metadata package target | `focusparse-paper-public-metadata-package-2026-05-26-v10` |

The current packages are suitable for review handoff and submission
preparation. They are not yet a final archival release because the worktree is
dirty and the final venue/anonymity/artifact policy is not selected.

## Archive Modes

| Mode | Path | Intended use |
| --- | --- | --- |
| Internal review | `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32.tar.gz` | Collaborator review, figure inspection, and paper-package handoff. Includes source-derived qualitative image assets. |
| Public metadata | `results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10.tar.gz` | Public, double-blind, or pre-clearance artifact staging. Excludes compiled PDFs and source-derived image/PDF files. |

The package helper writes a checksum sidecar next to each archive:

```text
<archive>.sha256
```

The checksum is intentionally stored beside the archive rather than embedded
inside it, because embedding an archive's own checksum would change the archive
bytes. Use the sidecar files when copying packages to external storage.

## Current Archive Commands

Internal review package:

```bash
uv run python scripts/package_paper_review_artifacts.py
```

Public-metadata package:

```bash
uv run python scripts/package_paper_review_artifacts.py --release-mode public-metadata
```

Expected sidecars after build:

```text
results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32.tar.gz.sha256
results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10.tar.gz.sha256
```

## Verification Checklist

After building packages, verify:

1. `manifest.json` exists inside each package.
2. The internal review package contains:
   - `paper-docs/latex/main.pdf`;
   - `paper-docs/compute-resource-disclosure.md`;
   - `paper-docs/source-pdf-and-asset-license-audit.md`;
   - `paper-docs/source-pdf-terms-manifest.tsv`;
   - `paper-docs/archival-snapshot-readiness.md`;
   - `results/headline/headline/headline_table.json`;
   - FocusParse +4 `per_example.jsonl`;
   - qualitative PNG assets for internal figure review.
3. The public-metadata package contains:
   - `paper-docs/compute-resource-disclosure.md`;
   - `paper-docs/source-pdf-and-asset-license-audit.md`;
   - `paper-docs/source-pdf-terms-manifest.tsv`;
   - `paper-docs/archival-snapshot-readiness.md`;
   - `paper-docs/references.bib`;
   - `results/headline/headline/headline_table.json`;
   - FocusParse +4 `per_example.jsonl`;
   - zero `.png`, `.jpg`, `.jpeg`, or `.pdf` files.
4. The `.tar.gz.sha256` sidecar exists for each archive.
5. `git diff --check` passes after the packaging edits.

## Final Archive Gate

Before submission or public release:

1. Select the target venue/workshop and artifact policy.
2. Decide whether to submit the internal review package, the public-metadata
   package, or a venue-specific artifact derived from one of them.
3. Commit or externally archive the exact code/docs used for the final result.
4. Record a clean commit SHA or archive DOI.
5. If the final package is public, keep uncleared source PDFs and
   source-derived page/crop/tile images out of the archive unless
   `source-pdf-and-asset-license-audit.md` has been completed for the relevant
   sources.
6. If the final result table is rerun, refresh this file, the compute
   disclosure, package docs, and checksums.

## Current Paper-Safe Statement

> The current workspace contains validated internal-review and public-metadata
> package modes. The public-metadata mode is the safer default for
> double-blind or public artifact staging because it contains run metadata,
> paper sources, diagnostics, and per-example outputs while excluding compiled
> PDFs and source-derived images. A final submission still requires a clean
> commit/tag or external archive DOI matching the chosen package.
