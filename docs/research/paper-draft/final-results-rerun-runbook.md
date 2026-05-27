# FocusParse Final Results Rerun Runbook

Date: 2026-05-24

Status: executable plan plus record of the first completed final paper result
package. This does not replace the current draft audits; it defines the
artifact bundle that must exist before the paper can make a main-table claim.

Completed package:

```text
results/hf/paper/2026-05-24-paper-headline-v1/
```

The completed package uses HF revision
`3774c67f8b814392b6d04c939e904f749a3f52eb`, staging root
`/Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb`,
PDF root `/Users/gabrielbo/.cache/focusparse/pdfs`, tier SHA `0b139a04`, and
`--max-parallel 2`. The main table and diagnostics are summarized in
`docs/research/paper-draft/final-headline-run-summary.md`.

## Purpose

The final paper should use one matched result package, not a mixture of
historical checkpoints. The package should prove the central claim under one
code SHA, one pinned Hugging Face dataset revision, one staged benchmark slice,
and one set of method definitions:

- Base VLM
- ReAct +2 tools
- ReAct +4 tools
- Agent baseline +2 tools
- Agent baseline +4 tools
- FocusParse +2 tools
- FocusParse +4 tools

The result table should report answer accuracy, cost/correct, latency, page
recall, and BBox IoU by domain and overall. The qualitative package should show
how inspect/expand produces compact evidence packets rather than isolated crops
or whole-page screenshots.

## Required Environment

Start from a clean shell in the repo root:

```bash
cd /Users/gabrielbo/projects/FocusParse
uv sync --extra dev
```

Required secrets:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
GOOGLE_API_KEY
HF_TOKEN
LAYOUT_EXTRACTION_V3_MODAL_TOKEN
```

Optional:

```text
LLAMA_CLOUD_API_KEY
```

The layout endpoint preflight is intentionally strict for FocusParse runs. Do
not use `--skip-layout-preflight` or `--allow-layout-fallbacks` for the final
paper table unless the paper explicitly labels the run as degraded.

## Choose Immutable IDs

Before running, choose a short slug and pin both code and data:

```bash
export PAPER_RUN_SLUG=2026-05-23-paper-headline-v1
export PAPER_HF_REVISION=3774c67f8b814392b6d04c939e904f749a3f52eb
export PAPER_STAGING=/Users/gabrielbo/.cache/focusparse/paper-${PAPER_HF_REVISION}
export PAPER_PDFS=/Users/gabrielbo/.cache/focusparse/pdfs
export PAPER_OUT=results/hf/paper/${PAPER_RUN_SLUG}
```

Record:

- current git commit SHA;
- `git status --short`;
- `configs/default.yaml`;
- `PAPER_HF_REVISION`;
- whether `PAPER_PDFS` contains all source PDFs used by the staged examples.

Current dataset pin from the no-model materialization pass:

```text
HF revision: 3774c67f8b814392b6d04c939e904f749a3f52eb
HF last modified: 2026-05-04 21:16:56+00:00
Staging root: /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb
Manifest: results/hf/paper/2026-05-23-revision-pin/dataset/materialization-summary.json
Benchmark SHA-256: e85b4df5032bc9e49fc74e1ed7492001794fbf4b46cc0f35d31a4cf32277962b
Dataset fingerprint: 835d8b90da8f7c1a
```

Current source-PDF readiness:

```text
PDF root: /Users/gabrielbo/.cache/focusparse/pdfs
Needed: 44
Present: 44
Missing: 0
Readiness manifest: results/hf/paper/2026-05-23-revision-pin/dataset/source-pdf-readiness.json
```

Current smoke readiness:

```text
Smoke summary: docs/research/paper-draft/pinned-smoke-run-summary.md
Smoke IDs: docs/research/paper-draft/smoke-example-ids.txt
Smoke result: results/hf/paper/2026-05-23-revision-pin/smoke-focus-full/focusparse_focus_agentic_multi_page_0b139a04/run.json
Smoke status: 3/3 correct, layout/model path successful, one Anthropic timeout recovered by retry
Headline smoke summary: docs/research/paper-draft/pinned-headline-smoke-summary.md
Headline smoke result: results/hf/paper/2026-05-23-revision-pin/headline-smoke/headline_table.json
Headline smoke status: all 7 configured method specs produced rows, staging remained 148 rows
```

## Materialize And Fingerprint The Dataset

Materialize the full pinned HF validation split into `PAPER_STAGING` without
spending model tokens. This writes `benchmark.jsonl` plus page PNGs. The loader
filters pre-baked stress rows and treats HF `validation` as the paper benchmark
split.

```bash
uv run python - <<'PY'
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from focusparse.eval.hf_loader import dataset_fingerprint, materialize_split

staging = Path(os.environ["PAPER_STAGING"])
out_dir = Path(os.environ["PAPER_OUT"]) / "dataset"
out_dir.mkdir(parents=True, exist_ok=True)

bench, ds = materialize_split(
    staging,
    repo_id="gabrielbo/parser-bench",
    split="validation",
    revision=os.environ["PAPER_HF_REVISION"],
    force=True,
)
fingerprint = dataset_fingerprint(ds)
rows = [json.loads(line) for line in bench.read_text().splitlines() if line.strip()]
ids = [r["id"] for r in rows]
summary = {
    "benchmark_jsonl": str(bench),
    "benchmark_sha256": hashlib.sha256(bench.read_bytes()).hexdigest(),
    "dataset_fingerprint": fingerprint,
    "rows": len(rows),
    "unique_ids": len(set(ids)),
    "duplicate_ids": [k for k, v in Counter(ids).items() if v > 1],
    "domains": dict(Counter(r.get("domain") for r in rows)),
    "stress_types": dict(Counter(r.get("stress_type") for r in rows)),
    "source_pdfs": len({r.get("source_pdf") for r in rows if r.get("source_pdf")}),
}
(out_dir / "materialization-summary.json").write_text(json.dumps(summary, indent=2))
(out_dir / "fingerprint.json").write_text(json.dumps(fingerprint, indent=2))
(out_dir / "benchmark.sha256").write_text(summary["benchmark_sha256"] + "\n")
print(json.dumps(summary, indent=2))
PY
```

Then verify the canonical slice:

```bash
wc -l "${PAPER_STAGING}/benchmark.jsonl"
uv run python - <<'PY'
import json
from collections import Counter
from pathlib import Path
import os

bench = Path(os.environ["PAPER_STAGING"]) / "benchmark.jsonl"
rows = [json.loads(line) for line in bench.read_text().splitlines() if line.strip()]
ids = [r["id"] for r in rows]
print("rows", len(rows))
print("unique_ids", len(set(ids)))
print("duplicate_ids", [k for k, v in Counter(ids).items() if v > 1])
print("domains", Counter(r.get("domain") for r in rows))
print("stress_types", Counter(r.get("stress_type") for r in rows))
print("source_pdfs", len({r.get("source_pdf") for r in rows if r.get("source_pdf")}))
PY
```

Acceptance target for the current paper slice:

- 148 rows;
- 147 unique example IDs;
- duplicate ID `dat-DS5091D-00-0016`;
- stress type `none` for every row;
- 101 datasheet rows and 47 finance rows.

If any count differs, stop and update `dataset-characterization.md` before
using the result in the paper.

## Hydrate Source PDFs

The HF dataset ships page images. Source PDFs are needed when the FocusParse
router should use the native text-index path instead of the all-pages fallback.
Hydrate them from NFS after the pinned staging file exists:

```bash
uv run python scripts/source_pdfs_from_nfs.py \
  --staging-dir "${PAPER_STAGING}" \
  --dest "${PAPER_PDFS}"
```

Record the success/failure summary. If any PDF is missing, either recover it
before the final table or state in the result manifest that the affected run did
not use the source-PDF text path.

The current pinned slice has already been hydrated successfully: 32 PDFs were
already present and 12 finance PDFs were pulled from the NFS
`archive/raw_pdfs/` fallback. See `source-pdf-readiness.md`.

## Smoke The Final Configuration

Run a small FocusParse smoke with the exact final paths and strict layout
preflight. Use `--example-ids-file`, not `--limit`, when sharing the final
`PAPER_STAGING` root; `--limit` rewrites `benchmark.jsonl` to a smaller staged
set.

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision "${PAPER_HF_REVISION}" \
  --staging-dir "${PAPER_STAGING}" \
  --pdfs-root "${PAPER_PDFS}" \
  --output-dir "${PAPER_OUT}/smoke-focus-full" \
  --example-ids-file docs/research/paper-draft/smoke-example-ids.txt \
  --no-resume
```

Check:

- the run exits cleanly;
- `run.json` and `per_example.jsonl` exist under the spec directory;
- `per_example.jsonl` has 3 rows;
- `${PAPER_STAGING}/benchmark.jsonl` still has 148 rows after the run;
- no layout preflight fallback or full-page-stub warning appears.

## Run The Seven-Method Headline Table

The orchestrator below runs all seven method/tool-set specs under the
`agentic_multi_page` protocol and merges them into `headline_table.json`. It
computes the current tier SHA from the same config/env path used by
`run_hf_eval.py`; use the emitted `tier_sha8` value when expanding the `<tier>`
placeholder in artifact paths.

```bash
uv run python scripts/run_headline_eval.py \
  --output-dir "${PAPER_OUT}/headline" \
  --staging-dir "${PAPER_STAGING}" \
  --pdfs-root "${PAPER_PDFS}" \
  --hf-revision "${PAPER_HF_REVISION}" \
  --max-parallel 4 \
  --no-resume \
  --render
```

For a seven-method smoke before the full run, add:

```bash
  --example-ids-file docs/research/paper-draft/smoke-example-ids.txt
```

Do not use `--limit` with the shared final staging root; use a separate staging
root if a limit-based smoke is ever needed.

If rate limits are tight, lower `--max-parallel` to `1` or `2`. Do not mix
rows from different runs in the final table; rerun failed specs into the same
result directory only when the code, config, HF revision, and staging path are
unchanged.

Expected outputs:

```text
${PAPER_OUT}/headline/headline_table.json
${PAPER_OUT}/headline/headline_table.md
${PAPER_OUT}/headline/headline_table.csv
${PAPER_OUT}/headline/headline_table.jsonl
${PAPER_OUT}/headline/headline_table.html
${PAPER_OUT}/headline/focusparse_simple_agentic_multi_page_<tier>/
${PAPER_OUT}/headline/focusparse_react_agentic_multi_page_<tier>_tminimal/
${PAPER_OUT}/headline/focusparse_react_agentic_multi_page_<tier>/
${PAPER_OUT}/headline/focusparse_agent_baseline_agentic_multi_page_<tier>_tminimal/
${PAPER_OUT}/headline/focusparse_agent_baseline_agentic_multi_page_<tier>/
${PAPER_OUT}/headline/focusparse_focus_agentic_multi_page_<tier>_tminimal/
${PAPER_OUT}/headline/focusparse_focus_agentic_multi_page_<tier>/
```

Every spec directory should contain:

```text
run.json
per_example.jsonl
predictions/
```

## Render Or Re-render Tables

If `--render` was not used, render the merged table explicitly:

```bash
uv run python scripts/render_headline_table.py \
  "${PAPER_OUT}/headline/headline_table.json"
```

The Markdown table is the paper source of truth for the draft. The CSV/JSONL
exports are for spreadsheets, plots, and statistical checks.

## Generate Diagnostics

Use the prediction miner on the headline parent directory:

```bash
uv run python scripts/diagnose_predictions.py \
  --spec-dir "${PAPER_OUT}/headline" \
  --output "${PAPER_OUT}/diagnostics/headline-diagnosis.md"
```

Keep both files:

```text
${PAPER_OUT}/diagnostics/headline-diagnosis.md
${PAPER_OUT}/diagnostics/headline-diagnosis.json
```

The diagnosis should be used for:

- lazy-answer rates;
- premature-final rates for comparator agents;
- tool-error rates;
- expand_context usage;
- packet text/context/chart coverage;
- failure taxonomy counts.

## Export Qualitative Viewers

Use the final FocusParse +4 spec directory from the headline run. Replace the
`<tier>` path segment after the table has finished.

```bash
uv run python scripts/build_agent_eyes_audit.py \
  --spec-dir "${PAPER_OUT}/headline/focusparse_focus_agentic_multi_page_<tier>" \
  --output-dir "${PAPER_OUT}/figures/agent-eyes" \
  --staging-root "${PAPER_STAGING}" \
  --include-correct \
  --limit 0 \
  --example-id fin-bis_qr_2025_mar-0050 \
  --example-id dat-JESD204B-Survival-Guide-0029 \
  --example-id dat-adrv9040-reference-manual-ug-2192-0032 \
  --example-id dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0052
```

Expected outputs:

```text
${PAPER_OUT}/figures/agent-eyes/index.html
${PAPER_OUT}/figures/agent-eyes/agent_eyes_audit.jsonl
${PAPER_OUT}/figures/agent-eyes/examples/*.html
```

Update `qualitative-figure-manifest.md` with the final paths and note whether
each figure uses selected crops, page overlays, or both.

## Compose Qualitative Figure Panels

After the viewer/page-crop bundle is generated, compose the draft paper panels:

```bash
uv run python scripts/build_paper_qualitative_panels.py \
  --bundle-dir "${PAPER_OUT}/figures/paper-final-qualitative-assets" \
  --output-dir "${PAPER_OUT}/figures/qualitative-figure-panels"
```

For the current local paper package, the equivalent command was:

```bash
uv run python scripts/build_paper_qualitative_panels.py --bundle-dir results/trace_viewer/paper-final-qualitative-assets --output-dir results/paper/qualitative-figure-panels
```

Expected outputs:

```text
${PAPER_OUT}/figures/qualitative-figure-panels/figure3-finance-latvia-evidence-binding.png
${PAPER_OUT}/figures/qualitative-figure-panels/figure4-datasheet-jesd204b-evidence-binding.png
${PAPER_OUT}/figures/qualitative-figure-panels/asset-inventory.csv
${PAPER_OUT}/figures/qualitative-figure-panels/presentation-visuals.md
```

## Export Qualitative Baseline Comparisons

Generate same-revision method predictions for the main qualitative examples:

```bash
uv run python scripts/build_qualitative_baseline_comparison.py \
  --headline-dir "${PAPER_OUT}/headline" \
  --output-dir "${PAPER_OUT}/figures/qualitative-baseline-comparisons"
```

For the current local paper package, the equivalent command was:

```bash
uv run python scripts/build_qualitative_baseline_comparison.py --headline-dir results/hf/paper/2026-05-24-paper-headline-v1/headline --output-dir results/paper/qualitative-baseline-comparisons
```

Expected outputs:

```text
${PAPER_OUT}/figures/qualitative-baseline-comparisons/qualitative-baseline-comparison.md
${PAPER_OUT}/figures/qualitative-baseline-comparisons/qualitative-baseline-comparison.csv
```

## Build A Slim Review Package

The full headline result package is intentionally large because it stores
intermediate tiles and prediction payloads. For review handoffs, build a slim
package that preserves the paper docs, headline tables, every method's
`run.json` / `per_example.jsonl`, diagnostics, figure panels, baseline
comparisons, and the lighter qualitative trace-viewer assets:

```bash
uv run python scripts/package_paper_review_artifacts.py
```

Current output:

```text
results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32/
results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32.tar.gz
results/paper/submission-review-package/focusparse-paper-review-package-2026-05-24-v32.tar.gz.sha256
```

The generated directory is 116M, the archive is 46M, and
`manifest.json` records file-level checksums, including the
venue-template conversion audit, NeurIPS-style checklist prep,
compute/resource disclosure, source-PDF/asset license audit, source-PDF terms
manifest, and archival snapshot readiness notes. The helper also writes a
sibling `.tar.gz.sha256` archive checksum sidecar. See
`docs/research/paper-draft/submission-review-package.md`.

To build the source-safer public-metadata package, which excludes compiled PDFs
and source-derived page/crop/tile/figure-panel images:

```bash
uv run python scripts/package_paper_review_artifacts.py --release-mode public-metadata
```

Current public-metadata output:

```text
results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10/
results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10.tar.gz
results/paper/submission-review-package/focusparse-paper-public-metadata-package-2026-05-26-v10.tar.gz.sha256
```

The public-metadata archive is 8.8M, has 106 manifest-tracked files, and has
150 tar members. Validation found no `.png`, `.jpg`, `.jpeg`, or `.pdf` files.

## Suggested Result Package Layout

The final artifact directory should look like this:

```text
results/hf/paper/${PAPER_RUN_SLUG}/
  README.md
  manifest.json
  git_status.txt
  config/
    default.yaml
  dataset/
    fingerprint.json
    materialization-summary.json
    benchmark.sha256
  headline/
    headline_table.json
    headline_table.md
    headline_table.csv
    headline_table.jsonl
    headline_table.html
    focusparse_*_agentic_multi_page_*/
      run.json
      per_example.jsonl
      predictions/
  diagnostics/
    headline-diagnosis.md
    headline-diagnosis.json
  figures/
    agent-eyes/
      index.html
      agent_eyes_audit.jsonl
      examples/
```

Minimum `manifest.json` fields:

```json
{
  "paper_run_slug": "2026-05-23-paper-headline-v1",
  "generated_at": "YYYY-MM-DDTHH:MM:SSZ",
  "git_commit": "<sha>",
  "git_status_short": "<path or embedded string>",
  "hf_repo": "gabrielbo/parser-bench",
  "hf_split": "validation",
  "hf_revision": "<hf_dataset_commit_sha>",
  "staging_dir": "/Users/gabrielbo/.cache/focusparse/paper-<revision>",
  "pdfs_root": "/Users/gabrielbo/.cache/focusparse/pdfs",
  "canonical_rows": 148,
  "canonical_unique_ids": 147,
  "duplicate_ids": ["dat-DS5091D-00-0016"],
  "stress_filter": "keep stress_type in [null, '', 'none']",
  "headline_table": "headline/headline_table.json",
  "diagnostics": "diagnostics/headline-diagnosis.md",
  "notes": []
}
```

## Acceptance Checks

Do not update the submission draft until all checks pass:

1. `headline_table.json` has exactly seven rows matching the seven configured
   method specs.
2. Every method `per_example.jsonl` has 148 rows.
3. Every method `run.json` reports the same HF repo, split, revision, protocol,
   and tier SHA shape expected by the manifest.
4. The materialized benchmark has 148 rows and 147 unique IDs.
5. FocusParse +4 has nonzero page recall and BBox IoU; comparator localizers
   are not silently missing citation/bbox fields due to schema drift.
6. Diagnostics exist and include all seven methods.
7. Qualitative figure viewers are regenerated from the final FocusParse +4
   spec, not from an older checkpoint.
8. `artifact-provenance-audit.md`, `experiments-results-audit.md`,
   `qualitative-figure-manifest.md`, and `focusparse-submission-draft.md` are
   updated to point at the final package.
9. The slim review package has been generated, and its manifest contains the
   paper PDF, headline table, all seven method `run.json` files, and all seven
   method `per_example.jsonl` files.

## Claim Rules

Use the final package to set the paper claim strength:

- If the final all-method table is complete and FocusParse +4 wins the matched
  accuracy/cost/localization comparison, the abstract can make the full
  performance claim.
- If a future rerun invalidates the current matched table, fall back to the
  latest raw-verified FocusParse-only checkpoint and label any all-comparator
  claim as pending.
- If the 66.9% candidate is recovered or rerun, use it only when the raw
  `run.json`, `per_example.jsonl`, code SHA, HF revision, and materialization
  logs are all inside this package or linked from it.

## Common Failure Modes

- Cached predictions can hide scorer or answer-shape changes. Use a fresh
  `PAPER_OUT` and `--no-resume` for final results.
- Missing `PAPER_PDFS` changes the FocusParse routing path. Hydrate PDFs or
  record the fallback explicitly.
- Layout endpoint stubs create whole-page crops. The final table should fail
  fast on layout preflight rather than continue with fallback evidence.
- Gemini can produce empty visible responses when thinking budget is too low.
  Keep the configured model settings aligned with `configs/default.yaml`.
- GPT-5.x uses `max_completion_tokens`, not the older `max_tokens` parameter.
- Zotero export is separate from the result package; bibliography readiness
  should not block generating the table, but it does block final submission.
