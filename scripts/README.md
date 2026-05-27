# Scripts

Use these entrypoints from the repo root with `uv run python`.

## Core Evaluation

| Script | Purpose |
| --- | --- |
| `run_hf_eval.py` | Run one method/protocol/tool-set config against parser-bench. |
| `run_headline_eval.py` | Run the seven-method paper table. |
| `render_headline_table.py` | Render `headline_table.json` to Markdown/HTML/CSV-style views. |
| `source_pdfs_from_nfs.py` | Hydrate source PDFs for native text routing. |
| `fetch_nfs_processed.py` | Pull processed document assets from NFS. |

## Analysis

| Script | Purpose |
| --- | --- |
| `compare_headline_tables.py` | Compare two headline tables. |
| `summarize_headline_replicates.py` | Aggregate repeated headline runs. |
| `build_paper_ablation_summary.py` | Pair +2/+4 or mechanism ablation rows. |
| `build_paper_failure_taxonomy.py` | Summarize final FocusParse error buckets. |
| `diagnose_predictions.py` | Inspect prediction-level failure modes. |
| `diff_runs.py` | Compare two result directories row by row. |
| `rescore_predictions.py` | Re-score existing prediction artifacts. |

## Demos And Artifacts

| Script | Purpose |
| --- | --- |
| `visualize_trace.py` | Render trace HTML for one example. |
| `build_pipeline_demo.py` | Build the static demo bundle from run artifacts. |
| `build_paper_qualitative_panels.py` | Compose qualitative paper panels. |
| `build_qualitative_baseline_comparison.py` | Compare qualitative baseline predictions. |
| `package_paper_review_artifacts.py` | Build a slim local paper review package. |
| `export_traces.py` | Export SFT-ready trace JSONL. |

## Legacy Helpers

Files prefixed with `_60plus_` and older prompt/debug scripts are retained for
historical reproducibility. Prefer the core scripts above for new runs.
