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
| LlamaIndex ReAct +2 | 13.9% | 8.5% | 12.2% | 29.92s | $6.36 | $0.353 | 148 |
| LlamaIndex ReAct +4 | 6.9% | 4.3% | 6.1% | 34.37s | $8.25 | $0.917 | 148 |
| Coding Agent +4 | 1.0% | 0.0% | 0.7% | 7.70s | $2.22 | $2.223 | 148 |
| DocLens-style | 21.8% | 4.3% | 16.2% | 21.70s | $3.74 | $0.156 | 148 |
| AgenticOCR-style | 24.8% | 4.3% | 18.2% | 10.21s | $2.13 | $0.079 | 148 |
| FocusParse +4 | 66.3% | 53.2% | 62.2% | 4.10s | $2.18 | $0.024 | 148 |

The generated table with bootstrap confidence intervals is available at
`results/hf/related-work-monitor/headline_table.md` in the monitor worktree.

## Interpretation

FocusParse beats the no-tool VLM by **+14.9 accuracy points** overall on the
current pinned revision, while keeping mean latency close to the basic row
(`4.10s` vs `3.41s`). The no-tool baseline is still the strongest comparator
after FocusParse, which is useful for the paper: the improvement is not merely
from adding more tools or model calls.

The trusted LlamaIndex ReAct comparison is especially important. The `+2`
version uses `inspect_region` and `get_text_layer`; the `+4` version adds
`layout_detect` and `run_python`. Both are dramatically below FocusParse, and
the larger tool set regresses from `12.2%` to `6.1%` while increasing total
cost from `$6.36` to `$8.25`. This supports the claim that industry-standard
ReAct-style tool access is not enough for localized parsing unless the system
has a budget-aware document-routing and evidence-packet architecture.

The DocLens-style and AgenticOCR-style rows are labeled faithful proxies, not
official paper reproductions. They are still useful for related work: both
embody prior ideas that FocusParse builds on, but neither reaches the current
FocusParse row on this benchmark. AgenticOCR-style is the stronger proxy
overall at `18.2%`, largely because query-conditioned crop/OCR behavior is a
better match to parser-bench than the DocLens-style page/evidence sampler.

## Provenance

Decision-grade artifacts are gitignored but preserved locally in each worktree:

| Row | Artifact |
| --- | --- |
| Basic VLM | `/private/tmp/focusparse-exp-basic-vlm-protocols/results/hf/related-work/basic_vlm/focusparse_simple_agentic_multi_page_0b139a04/` |
| LlamaIndex ReAct +2 | `/private/tmp/focusparse-exp-llamaindex-react/results/hf/related-work/llamaindex_react_minimal/focusparse_llamaindex_react_agentic_multi_page_0b139a04_tminimal/` |
| LlamaIndex ReAct +4 | `/private/tmp/focusparse-exp-llamaindex-react/results/hf/related-work/llamaindex_react_full/focusparse_llamaindex_react_agentic_multi_page_0b139a04/` |
| Coding Agent +4 | `/private/tmp/focusparse-exp-coding-agent/results/hf/related-work/coding_agent/focusparse_coding_agent_agentic_multi_page_0b139a04/` |
| DocLens-style | `/private/tmp/focusparse-exp-doclens-baseline/results/hf/related-work/doclens/focusparse_doclens_agentic_multi_page_0b139a04/` |
| AgenticOCR-style | `/private/tmp/focusparse-exp-agenticocr-baseline/results/hf/related-work/agentic_ocr/focusparse_agentic_ocr_agentic_multi_page_0b139a04/` |
| FocusParse +4 | `/private/tmp/focusparse-exp-related-work-monitor/results/hf/related-work/focusparse_reference/focusparse_focus_agentic_multi_page_0b139a04/` |

Historical FocusParse checkpoint: `99/148 = 66.9%` remains linked to
`/Users/gabrielbo/projects/FocusParse/results/hf/sprint-2026-05-15/answer-shape-normalizer-oai-run2/focusparse_focus_agentic_multi_page_8c5e328d.json`.
Use that row only when explicitly labeled as the recovered May 15 historical
checkpoint; the table above uses the current pinned-revision reproduction.
