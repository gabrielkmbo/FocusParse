# FocusParse Pinned Dataset Provenance

Date: 2026-05-23

Status: current pinned parser-bench materialization for the paper result
package. This is the no-model-cost provenance step from
`final-results-rerun-runbook.md`; it does not prove final method accuracy.

## External Pins

| Artifact | Pin |
| --- | --- |
| FocusParse public `main` | `1af7f2f413a7a228deb5644ddca67888d367a8f5` |
| Local checkout `HEAD` at inspection time | `1af7f2f413a7a228deb5644ddca67888d367a8f5` |
| `parse-bench` public `main` | `7685c36526b26bf3326a776c11f14354d506ebaa` |
| Hugging Face dataset | `gabrielbo/parser-bench` |
| HF split | `validation` |
| HF revision | `3774c67f8b814392b6d04c939e904f749a3f52eb` |
| HF last modified | `2026-05-04 21:16:56+00:00` |

Verification routes:

- GitHub connector commit search for `gabrielkmbo/FocusParse` and
  `gabrielkmbo/parse-bench`.
- `git ls-remote` against public `main` refs.
- Hugging Face connector dataset details.
- `huggingface_hub.HfApi().dataset_info("gabrielbo/parser-bench")`.

## Local Materialization

The pinned revision was materialized into:

```text
/Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl
```

The small manifest artifacts were written to:

```text
results/hf/paper/2026-05-23-revision-pin/dataset/materialization-summary.json
results/hf/paper/2026-05-23-revision-pin/dataset/fingerprint.json
results/hf/paper/2026-05-23-revision-pin/dataset/benchmark.sha256
results/hf/paper/2026-05-23-revision-pin/dataset/source-pdf-readiness.json
```

Because `results/` is gitignored, this Markdown file is the durable paper-draft
record of the pinned materialization. Rerun the materialization before the final
submission package if the paper code, HF revision, or staging root changes.

## Materialization Summary

| Field | Value |
| --- | ---: |
| Rows | 148 |
| Unique example IDs | 147 |
| Duplicate ID | `dat-DS5091D-00-0016` |
| Datasheet rows | 101 |
| Finance rows | 47 |
| Source PDFs | 44 |
| Stress type | 148 `none` |
| Dataset fingerprint | `835d8b90da8f7c1a` |
| Benchmark JSONL SHA-256 | `e85b4df5032bc9e49fc74e1ed7492001794fbf4b46cc0f35d31a4cf32277962b` |
| Source PDFs present | 44/44 |
| PDF root | `/Users/gabrielbo/.cache/focusparse/pdfs` |

Manifest payload:

```json
{
  "benchmark_jsonl": "/Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl",
  "benchmark_sha256": "e85b4df5032bc9e49fc74e1ed7492001794fbf4b46cc0f35d31a4cf32277962b",
  "dataset_fingerprint": {
    "num_rows": 148,
    "fingerprint": "835d8b90da8f7c1a",
    "split": "validation",
    "version": "0.0.0",
    "description": null
  },
  "hf_repo": "gabrielbo/parser-bench",
  "hf_split": "validation",
  "hf_revision": "3774c67f8b814392b6d04c939e904f749a3f52eb",
  "rows": 148,
  "unique_ids": 147,
  "duplicate_ids": [
    "dat-DS5091D-00-0016"
  ],
  "domains": {
    "datasheet": 101,
    "finance": 47
  },
  "stress_types": {
    "none": 148
  },
  "source_pdfs": 44
}
```

## Paper Use

Use this pinned dataset record for:

- the final dataset table row count and domain split;
- the final result package's `PAPER_HF_REVISION`;
- the final result package's staging root;
- the artifact-provenance appendix.

Do not use this file as evidence for method accuracy. Accuracy claims still
require a final seven-method headline table with raw `run.json` and
`per_example.jsonl` for every method.
