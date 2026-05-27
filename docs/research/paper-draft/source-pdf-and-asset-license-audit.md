# FocusParse Source PDF And Asset License Audit

Date: 2026-05-26

Status: release-risk audit for the pinned parser-bench paper slice and the
current paper review package. This is not legal advice and does not replace a
final venue/repository license review.

## Evidence Inspected

- Pinned paper materialization:
  `/Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl`
- Source-PDF hydration record:
  `docs/research/paper-draft/source-pdf-readiness.md`
- Per-PDF terms manifest:
  `docs/research/paper-draft/source-pdf-terms-manifest.tsv`
- Parser-bench high-resolution benchmark source/licensing spec:
  `third_party/parser-bench/docs/highres_benchmark_spec.md`
- FocusParse license statement:
  `README.md`
- Parser-bench submodule license statement:
  `third_party/parser-bench/README.md`
- Current slim review package:
  `results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32/`

## Current Known Facts

| Item | Current evidence | Release implication |
| --- | --- | --- |
| FocusParse code | `README.md` says Apache-2.0. | Code can be released under Apache-2.0, subject to dependency and secret cleanup. |
| Parser-bench code/submodule | `third_party/parser-bench/README.md` says MIT. | Submodule code license is permissive. |
| Pinned paper slice | 148 rows, 44 source PDFs, 101 datasheet rows, 47 finance rows. | Dataset metadata can be described precisely; source-document redistribution needs a separate per-source review. |
| Source-PDF cache | All 44 PDFs are present locally under `/Users/gabrielbo/.cache/focusparse/pdfs`. | Local reproducibility is ready; public redistribution is not automatically cleared. |
| Current review package images | The v32 package includes 146 derived image assets: 2 composed paper panels plus page renders, N-up tiles, and crops for 4 qualitative examples. | The current package is good for internal review, but should not be treated as a public artifact until asset terms are checked. |
| Current review package full PDFs | The slim package does not copy full source PDFs. | This is the safer default for public release. |
| Public-metadata package | `focusparse-paper-public-metadata-package-2026-05-26-v10` has 106 checksum-tracked files and no `.png`, `.jpg`, `.jpeg`, or `.pdf` files. | This is the safer starting point for public or anonymous artifact release. |
| Terms manifest | `source-pdf-terms-manifest.tsv` has one row per pinned source PDF with publisher/family, source URL, terms URL, redistribution status, verification status, and notes fields. | All 44 rows now have source and terms records: 42 official web-verified rows, 1 Nordic official-PDF/no-reproduction-notice row, and 1 TTP223B distributor-mirror row where no official manufacturer source was found. |

## Source-PDF Inventory By Release Risk

The materialized JSONL records `source_pdf` and `domain`, but not source URL,
publisher, license URL, or redistribution terms. The table below is therefore
a release-risk inventory, not a completed license clearance.

| Bucket | Source PDFs | Current release status |
| --- | ---: | --- |
| Datasheet / vendor / technical manuals and app notes | 29 | Publicly obtainable in many cases, but page/crop redistribution terms must be checked per publisher before releasing image assets. |
| Public financial or institutional reports | 10 | Official source and terms URLs are now recorded for these rows; derived page/crop redistribution still needs final policy review per source. |
| Public company filings / company reports | 3 | Official SEC source and access-policy URLs are now recorded; derived page/crop redistribution still needs final copyright review. |
| Commercial research / market guide PDFs | 2 | Highest caution bucket; avoid public redistribution of page images/crops until terms are verified. |

### Datasheet / Technical Sources

These 29 PDFs account for 101 rows:

```text
AN040_EN.pdf
Arm_EE382N_4.pdf
BCM2835-ARM-timer-int.annot.pdf
Buck Converter Selection Criteria _ Richtek Technology.pdf
DC_DC Converter Testing with Fast Load Transient _ Richtek Technology.pdf
DS5091D-00.pdf
DS8237AB-06.pdf
JESD204B-Survival-Guide.pdf
SG017_2022.pdf
TTP223B-data-sheet.pdf
adrv9008-1-w-9008-2-w-9009-w-hardware-reference-manual-ug-1295.pdf
adrv9040-reference-manual-ug-2192.pdf
ads1299.pdf
aducm350_ug-587.pdf
arm1176-ch13-debug.pdf
arm1176-ch3-coproc.annot.pdf
arm1176-vm.annot.pdf
armv6-interrupts.annot.pdf
armv6.b2-memory.annot.pdf
armv6.b3-coprocessor.annot.pdf
gmsl2-general-user-guide.pdf
infineon-applicationnote-linear-mode-operation-safe-operation-diagram-mosfets-applicationnotes-en.pdf
infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en.pdf
infineon-designing-with-power-mosfets-applicationnotes-en.pdf
infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en.pdf
nRF24L01P_PS_v1.0.annot.pdf
opa454.pdf
slvaer0b.pdf
spruhm8k.pdf
```

Paper-safe treatment:

- cite or name the source documents only when needed for qualitative examples;
- release row metadata, questions, answers, evidence pages, and bounding boxes;
- avoid redistributing full PDF files;
- avoid public redistribution of page renders, tiles, and crops until each
  publisher's terms are checked or the artifact is limited to anonymous/private
  review.

### Finance / Institutional Sources

These 15 PDFs account for 47 rows:

| Source PDF | Rows | Current category |
| --- | ---: | --- |
| `10-K.pdf` | 7 | Microsoft FY2025 Form 10-K; official SEC source/access-policy URLs recorded. |
| `aapl-20250927.pdf` | 6 | Apple FY2025 Form 10-K; official SEC source/access-policy URLs recorded. |
| `bis_ar_2024.pdf` | 1 | Public institutional report; official BIS source/terms URLs recorded. |
| `bis_qr_2024_sep.pdf` | 3 | Public institutional report; official BIS source/terms URLs recorded. |
| `bis_qr_2025_mar.pdf` | 5 | Public institutional report; official BIS source/terms URLs recorded. |
| `boe_fsr_2024_jun.pdf` | 2 | Public institutional report; official Bank of England source/legal URLs recorded. |
| `boe_fsr_2024_nov.pdf` | 2 | Public institutional report; official Bank of England source/legal URLs recorded. |
| `boj_fsr_2024_apr.pdf` | 1 | Public institutional report; official Bank of Japan source/terms URL recorded. |
| `boj_fsr_2024_oct.pdf` | 1 | Public institutional report; official Bank of Japan source/terms URL recorded. |
| `ecb_fsr_2024_may.pdf` | 1 | Public institutional report; official ECB source/terms URL recorded. |
| `fed_fsr_2023_apr.pdf` | 2 | Public institutional/government report; official Federal Reserve source/linking-policy URLs recorded. |
| `goog-20251231.pdf` | 6 | Alphabet FY2025 Form 10-K; official SEC source/access-policy URLs recorded. |
| `imf_weo_2024_oct.pdf` | 1 | Public institutional report; official IMF source/copyright URLs recorded. |
| `jpm_gtm_us_daily.pdf` | 7 | Commercial market-guide PDF; official JPM source/terms URLs recorded, but public release should remain metadata-only without explicit permission. |
| `jpm_ltcma.pdf` | 2 | Commercial research/market PDF; official JPM source/terms URLs recorded, but public release should remain metadata-only without explicit permission. |

Paper-safe treatment:

- use public source URLs and retrieval scripts where possible;
- keep full PDFs out of the public review package;
- for central-bank/institutional reports, record the exact source URL and terms
  in a future dataset card appendix;
- for JPM and other commercial research PDFs, prefer metadata-only release plus
  instructions for users to obtain the public PDF themselves.

## Current Review Package Asset Risk

Current v32 review package includes:

| Asset class | Count | Release risk |
| --- | ---: | --- |
| Composed qualitative panels | 2 | Suitable for paper figures after caption/source attribution and venue policy review. |
| Trace-viewer page renders, N-up tiles, and crops | 144 | Useful for internal/reviewer inspection; not cleared for public standalone release. |
| Full source PDFs | 0 | Not included; keep this exclusion for public release. |

Current public-metadata package includes no compiled PDF or source-derived
image files:

```text
results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10/
results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10.tar.gz
results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10.tar.gz.sha256
```

Validation summary:

| Field | Value |
| --- | ---: |
| Manifest-tracked files | 106 |
| Archive members | 150 |
| Directory size | 75M |
| Archive size | 8.8M |
| `.png` / `.jpg` / `.jpeg` / `.pdf` files | 0 |

Important detail: the trace-viewer assets are derived from four qualitative
examples:

```text
fin-bis_qr_2025_mar-0050
dat-JESD204B-Survival-Guide-0029
dat-adrv9040-reference-manual-ug-2192-0032
dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0052
```

These assets should be considered private/internal review artifacts until the
source-document terms are checked.

## Recommended Artifact Release Modes

| Mode | Contents | Use when |
| --- | --- | --- |
| Internal review package | Current v32 shape with page renders/crops and trace viewer assets. | Sharing privately with collaborators or reviewers when allowed by venue instructions. |
| Public-metadata package | Current public-metadata package with paper sources, run JSON, per-example rows, metrics, configs, scripts, manifest, and text/CSV analysis; no full PDFs, compiled PDF, or source-derived images. | Double-blind review, public artifact staging, or any sharing path before source-image redistribution is cleared. |
| Public archival package | Code, dataset metadata, questions/answers, source URLs, evidence page/bbox coordinates, run artifacts, and scripts to rehydrate PDFs; derived images only when source terms allow. | Camera-ready release, Zenodo/OSF/registry archive, or public GitHub/HF artifact. |

## Required Additions Before Public Release

1. Resolve the remaining non-official source caveat for
   `TTP223B-data-sheet.pdf` if an original manufacturer URL or permission
   contact becomes available. Until then, keep public artifacts metadata-only
   for that source.
2. Use `--release-mode public-metadata` as the default public artifact shape
   until source terms permit richer image assets.
3. Add a dataset-card section that distinguishes:
   - FocusParse code license;
   - parser-bench code license;
   - benchmark metadata license;
   - third-party document source terms.
4. Add source attribution in captions for qualitative figures.
5. If a venue allows a private review supplement, label the image-heavy package
   as review-only and avoid treating it as a public release artifact.

## Current Checklist Answer

For a NeurIPS-style checklist, the current truthful answer is:

> Code licenses are permissive: FocusParse is Apache-2.0 and the parser-bench
> submodule is MIT. The benchmark uses public or publicly obtainable finance
> and datasheet PDFs. The current source-PDF manifest records official source
> and terms URLs for 42 public finance, company-filing, institutional, and
> vendor-technical PDFs, plus one Nordic row whose official PDF contains a
> no-reproduction notice and one TTP223B row backed by a distributor mirror
> because no original manufacturer source was found. The public artifact should
> therefore release
> metadata, scripts, coordinates, metrics, and run outputs by default, while
> withholding full PDFs and derived page/crop/tile images unless the relevant
> source terms permit redistribution.
