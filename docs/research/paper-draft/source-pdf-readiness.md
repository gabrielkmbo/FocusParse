# FocusParse Source PDF Readiness

Date: 2026-05-23

Status: source-PDF hydration record for the pinned parser-bench paper slice.
This is a prerequisite for final FocusParse runs that should use the native
source-PDF text-index routing path.

## Summary

Pinned dataset:

```text
HF revision: 3774c67f8b814392b6d04c939e904f749a3f52eb
Benchmark JSONL: /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl
PDF root: /Users/gabrielbo/.cache/focusparse/pdfs
```

Readiness result:

| Field | Value |
| --- | ---: |
| Source PDFs needed | 44 |
| Present locally | 44 |
| Missing | 0 |
| Datasheet PDFs | 29 |
| Finance PDFs | 15 |
| Total local PDF bytes | 177,711,813 |

Machine-readable readiness artifact:

```text
results/hf/paper/2026-05-23-revision-pin/dataset/source-pdf-readiness.json
```

## Hydration Command

```bash
uv run python scripts/source_pdfs_from_nfs.py \
  --staging-dir /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb \
  --dest /Users/gabrielbo/.cache/focusparse/pdfs
```

Result:

```text
Done: 12 pulled, 32 skipped, 0 failed.
```

The initial run found all 29 datasheet PDFs and 3 finance PDFs already present,
but 12 finance PDFs were missing from the default `raw/finance/` NFS directory.
They were found under:

```text
llama-nfs:/home/osx-user/shared-experiments/llamacloud-bench-ci/data/parser-bench/archive/raw_pdfs/
```

`scripts/source_pdfs_from_nfs.py` now tries that archive location as a fallback
after the default `raw/{datasheets,finance}/` path fails.

## Archive Fallback PDFs

These were pulled from `archive/raw_pdfs/`:

| PDF | Domain |
| --- | --- |
| `bis_ar_2024.pdf` | finance |
| `bis_qr_2024_sep.pdf` | finance |
| `bis_qr_2025_mar.pdf` | finance |
| `boe_fsr_2024_jun.pdf` | finance |
| `boe_fsr_2024_nov.pdf` | finance |
| `boj_fsr_2024_apr.pdf` | finance |
| `boj_fsr_2024_oct.pdf` | finance |
| `ecb_fsr_2024_may.pdf` | finance |
| `fed_fsr_2023_apr.pdf` | finance |
| `imf_weo_2024_oct.pdf` | finance |
| `jpm_gtm_us_daily.pdf` | finance |
| `jpm_ltcma.pdf` | finance |

## Paper Use

The final headline run should pass:

```bash
--pdfs-root /Users/gabrielbo/.cache/focusparse/pdfs
```

This lets the FocusParse router use the source-PDF text path for every document
in the pinned 148-row slice. If the PDF cache is moved or cleared, rerun the
hydration command before launching final smoke or full headline evaluations.
