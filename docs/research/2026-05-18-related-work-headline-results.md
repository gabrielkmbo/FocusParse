# Related-Work Headline Results

Generated from the isolated related-work worktrees on 2026-05-18/19 using
`gabrielbo/parser-bench` validation revision
`3774c67f8b814392b6d04c939e904f749a3f52eb`. All decision-grade rows use the
canonical FocusParse post-filter denominator, `n=148`, under the headline
`agentic_multi_page` protocol.

## Core Thesis

The main result is not "tools help." It is that a query-conditioned,
stage-structured evidence localization harness helps. FocusParse is the only
method in this related-work sweep that combines high accuracy with low latency
and controlled evidence collection. Generic tool exposure through a trusted
LlamaIndex ReAct loop is substantially worse and more expensive, and the
DocLens/AgenticOCR faithful proxies confirm that hierarchical localization
ideas help only when the harness is tuned to the benchmark's evidence contract.

## Headline Table

| Method | Datasheets accuracy | Finance accuracy | Overall accuracy | Overall latency | Cost | Cost/correct | n |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Basic VLM | 51.5% | 38.3% | 47.3% | 3.41s | $0.67 | $0.010 | 148 |
| LlamaIndex ReAct +2 | 14.9% | 6.4% | 12.2% | 29.65s | $6.38 | $0.354 | 148 |
| LlamaIndex ReAct +4 | 11.9% | 6.4% | 10.1% | 30.13s | $7.79 | $0.520 | 148 |
| Coding Agent +4 | 32.7% | 10.6% | 25.7% | 18.17s | $5.42 | $0.143 | 148 |
| DocLens-style | 22.8% | 4.3% | 16.9% | 19.14s | $3.79 | $0.152 | 148 |
| AgenticOCR-style | 21.8% | 4.3% | 16.2% | 8.30s | $1.87 | $0.078 | 148 |
| FocusParse +4 | 70.3% | 59.6% | 66.9% | 3.70s | $2.30 | $0.0232 | 148 |

The generated table with bootstrap confidence intervals is available in the
gitignored live output at `results/hf/related-work-monitor/headline_table.md`
and in the committed GitHub snapshot at
`docs/research/related-work-monitor/headline_table.md`.

## Interpretation

FocusParse beats the no-tool VLM by **+19.6 accuracy points** overall in the
headline checkpoint, while keeping mean latency close to the basic row
(`3.70s` vs `3.41s`). The no-tool baseline is still the strongest comparator
after FocusParse, which is useful for the paper: the improvement is not merely
from adding more tools or model calls.

The trusted LlamaIndex ReAct comparison is especially important. The `+2`
version uses `inspect_region` and `get_text_layer`; the `+4` version adds
`layout_detect` and `run_python`. Both are dramatically below FocusParse, and
the larger tool set remains below the +2 setting (`12.2%` vs `10.1%`) while
increasing total cost from `$6.38` to `$7.79`. This supports the claim that
industry-standard
ReAct-style tool access is not enough for localized parsing unless the system
has a budget-aware document-routing and evidence-packet architecture.

The DocLens-style and AgenticOCR-style rows are labeled faithful proxies, not
official paper reproductions. They are still useful for related work: both
embody prior ideas that FocusParse builds on, but neither reaches the current
FocusParse row on this benchmark. DocLens-style and AgenticOCR-style are close
overall (`16.9%` and `16.2%` respectively), with DocLens retaining stronger
localization and AgenticOCR remaining cheaper but more prone to under-exploring
finance examples.

## Provenance

Decision-grade artifacts are gitignored but preserved locally in each worktree:

| Row | Artifact |
| --- | --- |
| Basic VLM | `/private/tmp/focusparse-exp-basic-vlm-protocols/results/hf/related-work/basic_vlm/focusparse_simple_agentic_multi_page_0b139a04/` |
| LlamaIndex ReAct +2 | `/private/tmp/focusparse-exp-llamaindex-react/results/hf/related-work-fixed-full/llamaindex_react_minimal/focusparse_llamaindex_react_agentic_multi_page_0b139a04_tminimal/` |
| LlamaIndex ReAct +4 | `/private/tmp/focusparse-exp-llamaindex-react/results/hf/related-work-fixed-full/llamaindex_react_full/focusparse_llamaindex_react_agentic_multi_page_0b139a04/` |
| Coding Agent +4 | `/private/tmp/focusparse-exp-coding-agent/results/hf/related-work-fixed-full/coding_agent/focusparse_coding_agent_agentic_multi_page_0b139a04/` |
| DocLens-style | `/private/tmp/focusparse-exp-doclens-baseline/results/hf/related-work-fixed-full/doclens/focusparse_doclens_agentic_multi_page_0b139a04/` |
| AgenticOCR-style | `/private/tmp/focusparse-exp-agenticocr-baseline/results/hf/related-work-fixed-full/agentic_ocr/focusparse_agentic_ocr_agentic_multi_page_0b139a04/` |
| FocusParse +4 headline checkpoint | `shape-normalizer-full-run1`, documented in `docs/research/2026-05-15-harness-65plus-post-evidence-iteration.md` |

The older monitor reproduction remains preserved at
`/private/tmp/focusparse-exp-related-work-monitor/results/hf/related-work/focusparse_reference/focusparse_focus_agentic_multi_page_0b139a04/`
with `92/148 = 62.2%`; the table above uses the stronger weekend
`shape-normalizer-full-run1` checkpoint supplied for the presentation headline.

The pinned canonical slice has 148 rows and 147 unique example IDs because
`dat-DS5091D-00-0016` appears twice. The committed monitor snapshot records
that duplicate in `docs/research/related-work-monitor/dataset_manifest.json`.
