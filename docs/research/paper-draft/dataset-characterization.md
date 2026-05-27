# FocusParse Paper Dataset Characterization

Date: 2026-05-22

Status: current characterization of the canonical 148-row parser-bench paper
slice from a pinned local materialized `benchmark.jsonl`.

## Source

Current pinned paper materialization:

```text
HF repo: gabrielbo/parser-bench
HF split: validation
HF revision: 3774c67f8b814392b6d04c939e904f749a3f52eb
HF last modified: 2026-05-04 21:16:56+00:00
Benchmark JSONL: /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl
Dataset fingerprint: 835d8b90da8f7c1a
SHA-256: e85b4df5032bc9e49fc74e1ed7492001794fbf4b46cc0f35d31a4cf32277962b
Manifest: results/hf/paper/2026-05-23-revision-pin/dataset/materialization-summary.json
```

The default staging file currently has only 1 row and should not be used for
paper counts:

```text
/Users/gabrielbo/.cache/focusparse/hf_staging/benchmark.jsonl
```

The following five related-work materializations are byte-identical 148-row
files and match the canonical paper slice:

```text
/Users/gabrielbo/.cache/focusparse/hf_staging_related_work_fixed_full_llamaindex_full/benchmark.jsonl
/Users/gabrielbo/.cache/focusparse/hf_staging_related_work_fixed_full_doclens/benchmark.jsonl
/Users/gabrielbo/.cache/focusparse/hf_staging_related_work_fixed_full_agenticocr/benchmark.jsonl
/Users/gabrielbo/.cache/focusparse/hf_staging_related_work_fixed_full_coding_agent/benchmark.jsonl
/Users/gabrielbo/.cache/focusparse/hf_staging_related_work_fixed_full_llamaindex_minimal/benchmark.jsonl
```

SHA-256:

```text
e85b4df5032bc9e49fc74e1ed7492001794fbf4b46cc0f35d31a4cf32277962b
```

The statistics below were originally computed from a byte-identical
related-work materialization and now match the pinned paper materialization:

```text
/Users/gabrielbo/.cache/focusparse/hf_staging_related_work_fixed_full_agenticocr/benchmark.jsonl
/Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl
```

## Basic Counts

| Field | Value |
| --- | ---: |
| Rows | 148 |
| Unique example IDs | 147 |
| Duplicate ID | `dat-DS5091D-00-0016` appears 2 times |
| Source PDFs | 44 |
| Stress type | 148 `none` |
| HF split | 148 `validation` |

## Domain Mix

| Domain | Rows | Source PDFs | Multi-region | Multi-page | Requires visual |
| --- | ---: | ---: | ---: | ---: | ---: |
| Datasheet | 101 | 29 | 47 | 24 | 75 |
| Finance | 47 | 15 | 23 | 10 | 37 |
| Overall | 148 | 44 | 70 | 34 | 112 |

## Answer Types

| Answer type | Rows |
| --- | ---: |
| `exact_match` | 93 |
| `numeric` | 48 |
| `boolean` | 5 |
| `unanswerable` | 2 |

## Evidence Complexity

| Measure | Rows |
| --- | ---: |
| Single supporting page | 114 |
| Two supporting pages | 28 |
| Three supporting pages | 6 |
| Single supporting bbox | 77 |
| Two supporting bboxes | 39 |
| Three supporting bboxes | 26 |
| Four supporting bboxes | 6 |
| Evidence page spread = 0 | 114 |
| Evidence page spread > 0 | 34 |
| Evidence page spread >= 10 | 15 |
| Evidence page spread >= 50 | 6 |

Evidence page spread:

| Statistic | Value |
| --- | ---: |
| Min | 0 |
| Mean | 6.52 |
| Max | 269 |

## Difficulty

| Axis | Level 1 | Level 2 | Level 3 |
| --- | ---: | ---: | ---: |
| Visual | 37 | 54 | 57 |
| Reasoning | 6 | 40 | 102 |
| Localization | 27 | 72 | 49 |

Additional difficulty cuts:

| Cut | Rows |
| --- | ---: |
| Visual 3 and reasoning 3 and localization 3 | 26 |
| Visual 3 or localization 3 | 80 |
| Requires visual and multi-region | 49 |

## Question Families

| Family | Rows |
| --- | ---: |
| `axis_value_interpolation` | 26 |
| `near_miss_distractor` | 20 |
| `cross_page_continuation` | 19 |
| `min_typ_max_disambiguation` | 16 |
| `chart_table_cross_ref` | 13 |
| `figure_caption_cross_ref` | 9 |
| `chart_caption_fusion` | 7 |
| `confusable_label` | 7 |
| `multi_chart_comparison` | 7 |
| `table_note_fusion` | 6 |
| `dual_axis_disambiguation` | 4 |
| `footnote_critical` | 3 |
| `legend_series_binding` | 3 |
| `condition_footnote_fusion` | 2 |
| `curve_axis_reading` | 2 |
| `visual_table` | 2 |
| `chart_footnote_fusion` | 1 |
| `visual_line_chart` | 1 |

## Long-Spread Anchor Rows

These rows are useful for qualitative figures or slice analysis because their
supporting evidence spans widely separated pages.

| Example ID | Domain | Family | Spread | Supporting pages |
| --- | --- | --- | ---: | --- |
| `dat-aducm350_ug-587-0032` | datasheet | `min_typ_max_disambiguation` | 269 | `[16, 266, 285]` |
| `dat-adrv9040-reference-manual-ug-2192-0032` | datasheet | `chart_table_cross_ref` | 104 | `[10, 75, 114]` |
| `fin-bis_qr_2025_mar-0050` | finance | `cross_page_continuation` | 101 | `[8, 108, 109]` |
| `fin-10-K-0029` | finance | `confusable_label` | 71 | `[37, 108]` |
| `fin-fed_fsr_2023_apr-0052` | finance | `axis_value_interpolation` | 58 | `[17, 75]` |
| `dat-JESD204B-Survival-Guide-0029` | datasheet | `axis_value_interpolation` | 57 | `[16, 73]` |

## Paper Interpretation

This slice is small enough that the paper must report uncertainty and avoid
overclaiming domain-general performance. It is also concentrated enough to test
the paper's mechanism: nearly half the rows are multi-region, 112/148 require
visual evidence, 34/148 require multiple supporting pages, and the dominant
families are exactly the ones that stress inspection and context attachment
(`axis_value_interpolation`, `near_miss_distractor`,
`cross_page_continuation`, `min_typ_max_disambiguation`, and
`chart_table_cross_ref`).
