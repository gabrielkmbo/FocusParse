# FocusParse Final Headline Run Summary

Date: 2026-05-24

Status: raw artifact verified in this checkout. This is the first full matched
seven-method paper table regenerated under one code snapshot, one pinned
Hugging Face revision, one staged benchmark slice, and one source-PDF cache.

## Result Package

```text
results/hf/paper/2026-05-24-paper-headline-v1/
```

Key files:

- `README.md`
- `manifest.json`
- `config/default.yaml`
- `git_commit.txt`
- `git_status.txt`
- `headline/headline_table.json`
- `headline/headline_table.md`
- `headline/headline_table.csv`
- `headline/headline_table.jsonl`
- `headline/headline_table.html`
- `diagnostics/headline-diagnosis.md`
- `diagnostics/headline-diagnosis.json`

Every method directory under `headline/` contains `run.json`,
`per_example.jsonl`, and `predictions/`. Each `per_example.jsonl` has 148 rows.

## Pinned Inputs

| Item | Value |
| --- | --- |
| HF dataset | `gabrielbo/parser-bench` |
| HF revision | `3774c67f8b814392b6d04c939e904f749a3f52eb` |
| Staging root | `/Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb` |
| Benchmark JSONL SHA-256 | `e85b4df5032bc9e49fc74e1ed7492001794fbf4b46cc0f35d31a4cf32277962b` |
| PDF root | `/Users/gabrielbo/.cache/focusparse/pdfs` |
| Code commit recorded at run start | `1af7f2f413a7a228deb5644ddca67888d367a8f5` |
| Tier SHA | `0b139a04` |
| Protocol | `agentic_multi_page` |
| Max parallel | `2` |

The run-start `git_status.txt` records a dirty worktree with the paper package
and runbook/script changes in progress. This is paper-safe as an artifact
snapshot, but a submission archive should still package or commit the exact code
and docs used for the table.

## Dataset Shape

| Count | Value |
| --- | ---: |
| Rows | 148 |
| Unique IDs | 147 |
| Duplicate ID | `dat-DS5091D-00-0016` |
| Datasheet rows | 101 |
| Finance rows | 47 |
| Stress rows | 0 |
| Source PDFs | 44 |

## Headline Table

| Method | Overall acc | Datasheet acc | Finance acc | $/correct | BBox IoU | Page recall | Latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Base VLM | 43.9% | 47.5% | 36.2% | $0.0102 | 0.000 | 0.848 | 2.52s |
| ReAct +2 tools | 18.2% | 22.8% | 8.5% | $0.1341 | 0.336 | 0.819 | 14.00s |
| ReAct +4 tools | 16.2% | 20.8% | 6.4% | $0.1946 | 0.309 | 0.727 | 14.40s |
| Agent baseline +2 tools | 8.1% | 10.9% | 2.1% | $0.1324 | 0.000 | 0.000 | 5.21s |
| Agent baseline +4 tools | 6.1% | 7.9% | 2.1% | $0.1811 | 0.000 | 0.000 | 5.25s |
| Our harness +2 tools | 60.1% | 64.4% | 51.1% | $0.0282 | 0.897 | 0.929 | 3.30s |
| Our harness +4 tools | 61.5% | 66.3% | 51.1% | $0.0248 | 0.857 | 0.914 | 3.20s |

The rendered table includes 95% percentile-bootstrap confidence intervals
(1000 resamples, seed 42) for the domain and overall accuracy and
cost-per-correct cells.

## Main Interpretation

Paper-safe headline:

> On the pinned 148-row parser-bench paper slice, FocusParse +4 reaches 61.5%
> overall accuracy, 66.3% on datasheets, and 51.1% on finance, outperforming
> the base VLM by 17.6 points overall and generic tool-agent comparators by
> 43-55 points overall under the same protocol.

Mechanism evidence:

- FocusParse +4 keeps lazy-answer rate at 3.4%; FocusParse +2 is 2.7%.
- ReAct still makes tool calls but reaches only 16.2-18.2% accuracy.
- The generic agent baselines mostly terminate without useful tool use:
  diagnostics report 100% lazy-answer and empty-citation rates.
- FocusParse +4 builds 1184 evidence packets, calls `expand_context` on 100%
  of examples, attaches 9.72 neighbors on average, and its cited packets have
  100% text coverage plus 84.4% linked-context coverage.
- FocusParse +2 is already strong at 60.1%, but the +4 tool set improves
  datasheet accuracy and cost/correct while keeping finance accuracy flat.

Cost interpretation:

- Base VLM remains cheapest per correct at `$0.0102`, but with substantially
  lower accuracy and no region-evidence construction.
- FocusParse +4 is much cheaper per correct than the generic ReAct and generic
  agent baselines (`$0.0248` vs `$0.1324`-`$0.1946`) and is faster than ReAct
  (3.20s vs about 14s mean latency).

## Caveats

- The older documented 66.9% checkpoint remains unverified locally and should
  not be used as the submission headline unless recovered or rerun.
- The final package was generated from a dirty worktree. The result directory
  records the commit and dirty status; a submission artifact should also commit
  or externally archive the exact code and docs.
- Qualitative crop bundles, draft figure panels, and same-revision baseline
  comparisons have been generated and copied into the slim review package.
  Final camera-ready figure styling still depends on the selected venue
  template.
- Zotero export remains blocked until Zotero Desktop/local API is available.
- Mechanism ablations now include the paired +2/+4 tool-set row plus n=148
  no-expand, no-rerank, verifier-repair, and answer-shape-repair controls.
