# FocusParse Experiments And Results Audit

Date: 2026-05-24

Status: submission-planning audit for the paper Results section. This file
separates current raw artifacts, historical documented results, and experiments
that must be rerun before a workshop or conference submission.

## Current Result Evidence Tiers

| Result | Status | Source | Paper use |
| --- | --- | --- | --- |
| Final matched seven-method table | Raw artifact verified and slim review package generated | `results/hf/paper/2026-05-24-paper-headline-v1/headline/headline_table.json`, seven 148-row `per_example.jsonl` files, `diagnostics/headline-diagnosis.md`, and the latest archive under `results/paper/submission-review-package/` | Safe as the current main paper table; before submission, commit or externally archive the exact code/docs in addition to the slim package. |
| FocusParse 60.14% full run | Raw artifact verified, older checkpoint | `results/hf/sprint-2026-05-15/answer-shape-normalizer-oai-run2/focusparse_focus_agentic_multi_page_8c5e328d/run.json` and `per_example.jsonl` | Historical FocusParse checkpoint; superseded for headline use by the final matched table. |
| Older seven-row all-method table | Raw artifact verified, older checkpoint | `results/hf/headline-v1/headline_table.json` | Safe as historical mechanism evidence, but should not be mixed with the 60.14% FocusParse checkpoint as a matched final table. |
| Rebaseline-v2 seven-row diagnostic | Diagnostic / research-doc recorded | `results/diagnostics/rebaseline-v2/report.md`; raw `headline-v1-rebaseline-v2` directory absent | Useful for narrative and experiment design, not final main table. |
| FocusParse 66.9% full run | Documented but raw artifact missing locally | `docs/research/2026-05-15-harness-65plus-post-evidence-iteration.md` and `.claude/memory/project_changelog.md` | Candidate headline only; recover or rerun before treating as a paper result. |

## Final Matched Paper Table

Source:

```text
results/hf/paper/2026-05-24-paper-headline-v1/headline/headline_table.json
```

Evidence:

- `headline_table.{json,md,csv,jsonl,html}` all exist.
- Seven method directories contain `run.json`, `per_example.jsonl`, and
  `predictions/`.
- Each method `per_example.jsonl` has 148 rows.
- Staging `benchmark.jsonl` has 148 rows from HF revision
  `3774c67f8b814392b6d04c939e904f749a3f52eb`.
- Result root includes `README.md`, `manifest.json`, `git_commit.txt`,
  `git_status.txt`, and `config/default.yaml`.

Metrics:

| Method | Overall | Datasheet | Finance | $/correct | BBox IoU | Page recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Base VLM | 43.9% | 47.5% | 36.2% | $0.0102 | 0.000 | 0.848 |
| ReAct +2 | 18.2% | 22.8% | 8.5% | $0.1341 | 0.336 | 0.819 |
| ReAct +4 | 16.2% | 20.8% | 6.4% | $0.1946 | 0.309 | 0.727 |
| Agent baseline +2 | 8.1% | 10.9% | 2.1% | $0.1324 | 0.000 | 0.000 |
| Agent baseline +4 | 6.1% | 7.9% | 2.1% | $0.1811 | 0.000 | 0.000 |
| FocusParse +2 | 60.1% | 64.4% | 51.1% | $0.0282 | 0.897 | 0.929 |
| FocusParse +4 | 61.5% | 66.3% | 51.1% | $0.0248 | 0.857 | 0.914 |

Paper interpretation:

This table is now the submission-safe main result. It supports the claim that
structured evidence localization and compaction beat both no-tool VLM reasoning
and generic tool use on the concentrated finance/datasheet parser-bench slice.
The +4 tool set improves overall and datasheet accuracy over +2, while finance
accuracy remains tied. Base VLM remains cheapest per correct, so the paper
should frame FocusParse as an accuracy/localization win with lower cost than
generic tool agents, not as the cheapest possible row.

## Raw-Verified Historical FocusParse Checkpoint

Source:

```text
results/hf/sprint-2026-05-15/answer-shape-normalizer-oai-run2/focusparse_focus_agentic_multi_page_8c5e328d/
```

Evidence:

- `run.json` reports `n_examples = 148`.
- `per_example.jsonl` has 148 rows.
- Agent/protocol/model: `focus`, `agentic_multi_page`, `openai:gpt-5.4`.
- Tool set: `full`, with `inspect_region`, `get_text_layer`,
  `expand_context`, and `run_python` available.
- Focus feature flags in this run: `auto_zoom=false`,
  `chart_to_table_enabled=false`, `use_react_inspector=false`,
  `multi_scale_packets=false`, `use_evidence_graph=false`.

Metrics:

| Slice | n | Accuracy | Correct | Cost/correct | Latency | Page recall | BBox IoU | Lazy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Overall | 148 | 60.14% | 89/148 | $0.0243 | 4.26s | 0.892 | 0.870 | 0.041 |
| Datasheet | 101 | 63.37% | 64/101 | $0.0224 | 4.28s | 0.876 | 0.877 | 0.050 |
| Finance | 47 | 53.19% | 25/47 | $0.0292 | 4.22s | 0.926 | 0.856 | 0.021 |

Paper interpretation:

This remains useful historical evidence for the draft. It supports the claim
that a structured evidence harness can reach strong answer accuracy while
keeping localization quality high and lazy-answer rate low. It is no longer the
headline result because the May 24 matched seven-method table provides the
current same-revision comparator package.

## Raw-Verified Older All-Method Table

Source:

```text
results/hf/headline-v1/headline_table.json
```

Generated: 2026-04-29. Protocol: `agentic_multi_page`. Rows: 148.

| Method | Accuracy | Cost/correct | BBox IoU | Page recall |
| --- | ---: | ---: | ---: | ---: |
| Base VLM | 39.19% | $0.0115 | 0.061 | 0.874 |
| ReAct +2 | 16.22% | $0.0772 | 0.339 | 0.703 |
| ReAct +4 | 19.59% | $0.0679 | 0.339 | 0.732 |
| Agent baseline +2 | 12.16% | $0.0798 | 0.000 | 0.000 |
| Agent baseline +4 | 12.16% | $0.0820 | 0.000 | 0.000 |
| FocusParse +2 | 39.19% | $0.0194 | 0.708 | 0.798 |
| FocusParse +4 | 39.86% | $0.0190 | 0.712 | 0.768 |

Paper interpretation:

This table supports the mechanism story more than the final accuracy story.
Compared with ReAct and generic agents, FocusParse has far stronger BBox IoU
and competitive/lower cost per correct, even when final accuracy is close to
the base VLM. It shows that generic tool access does not automatically produce
localized, cited evidence. It should be labeled as an earlier checkpoint unless
regenerated against the final paper code and dataset revision.

## Documented 66.9% Candidate

Source:

```text
docs/research/2026-05-15-harness-65plus-post-evidence-iteration.md
.claude/memory/project_changelog.md
```

Documented metrics:

| Run | Correct | Accuracy | Datasheet | Finance | Cost/correct | Latency | Page recall | BBox IoU | Lazy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `shape-normalizer-full-run1` | 99/148 | 66.9% | 71/101 | 28/47 | $0.0232 | 3.70s | 0.949 | 0.881 | 0.020 |

Current problem:

No local raw result directory matching `shape-normalizer-full-run1` was found
under `results/`. Because `results/` is gitignored, this can happen even when
the research memo is accurate. The paper should not use this as a main result
until `run.json`, `per_example.jsonl`, code commit, HF revision, and
materialization logs are recovered or rerun.

## Required Submission Experiments

For a workshop/conference submission, rerun or recover:

1. Final matched seven-method table:
   completed at `results/hf/paper/2026-05-24-paper-headline-v1/`. Next action
   is to commit or externally archive the exact code/docs that produced the
   table; the slim review package has already been generated under
   `results/paper/submission-review-package/`.
2. Coarse tool-set ablation:
   completed from the final matched +2/+4 FocusParse per-example rows at
   `results/paper/ablation-summary/focusparse-toolset-ablation.md`. The paired
   comparison preserves duplicate IDs, covers all 148 rows, and reports 9
   recoveries, 7 regressions, and +2 net correct for +4 over +2.
3. Pure-ablation smoke checks:
   completed for no-expand, no-rerank, retry-off, and answer-shape-repair-off at
   `docs/research/paper-draft/ablation-smoke-summary.md`; these verify the
   CLI switches on the pinned setup but are not a substitute for n=148 mechanism
   ablations.
4. No-expand mechanism ablation:
   completed at `results/hf/paper/ablation-no-expand-v1/` with paired analysis
   in `results/paper/mechanism-ablation/no-expand-v1/`. Restoring expansion
   moves 59.5% to 61.5% overall, with 14 recoveries, 11 regressions, and +3 net
   correct rows.
5. No-rerank mechanism ablation:
   completed at `results/hf/paper/ablation-no-rerank-v1/` with paired analysis
   in `results/paper/mechanism-ablation/no-rerank-v1/`. Restoring rerank moves
   56.1% to 61.5% overall, with 19 recoveries, 11 regressions, and +8 net
   correct rows.
6. Verifier-directed repair ablation:
   completed at `results/hf/paper/ablation-verifier-off-v1/` with paired
   analysis in `results/paper/mechanism-ablation/verifier-off-v1/`. Restoring
   repair moves 62.8% to 61.5% overall in this run, with 9 recoveries,
   11 regressions, and -2 net correct rows. Treat this as a mixed/negative
   control showing that the current paper gain is not carried by repair.
7. Answer-shape repair ablation:
   completed at `results/hf/paper/ablation-answer-shape-off-v1/` with paired
   analysis in `results/paper/mechanism-ablation/answer-shape-off-v1/`.
   Restoring answer-shape-specific repair moves 64.2% to 61.5% overall in this
   run, with 9 recoveries, 13 regressions, and -4 net correct rows. Treat this
   as a negative control showing that scorer-shape normalization is not carrying
   the verified paper gain.
8. Strongest FocusParse checkpoint:
   recover/rerun `shape-normalizer-full-run1` only if the paper wants to
   supersede the final matched 61.5% headline.
9. Slice diagnostics:
   finance vs datasheet, chart families vs table/text families, multi-region
   vs single-region, high evidence-page-spread vs low-spread, and lazy vs
   non-lazy examples.
10. Qualitative figure export:
   page/crop overlays for the Latvia finance example, the JESD204B cross-page
   datasheet success example, and the Q1/Q2 near-miss visual example; keep
   ADRV9040 as an optional answer-shape/field-preservation analysis case.

Recommended command entrypoints:

```bash
uv run python scripts/run_headline_eval.py --output-dir results/hf/<paper-headline-dir> --hf-revision <revision>
uv run python scripts/render_headline_table.py results/hf/<paper-headline-dir>/headline_table.json
uv run python scripts/diagnose_predictions.py --spec-dir results/hf/<paper-headline-dir> --output results/hf/<paper-headline-dir>/diagnostics/headline-diagnosis.md
```

The final submission package should keep the exact `run.json`,
`per_example.jsonl`, rendered headline table, diagnostic report, and figure
source examples together under one result directory.

For the full command sequence and artifact layout, use
`docs/research/paper-draft/final-results-rerun-runbook.md`.
