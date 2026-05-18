# Related-Work Experiment Monitor

This branch is the consolidation branch for the parallel related-work runs.
It does not implement new methods. It tracks commands, run health, dataset
identity, and thesis-facing result tables.

## Branch Roles

| Branch | Method | Owner |
| --- | --- | --- |
| `codex/exp-basic-vlm-protocols` | no-tool VLM protocol matrix | basic VLM worker |
| `codex/exp-llamaindex-react` | trusted LlamaIndex ReAct +2/+4 | ReAct worker |
| `codex/exp-coding-agent` | Gemini Agentic Vision style coding loop | coding-agent worker |
| `codex/exp-doclens-baseline` | DocLens-style faithful proxy | DocLens worker |
| `codex/exp-agenticocr-baseline` | AgenticOCR-style faithful-lite proxy | AgenticOCR worker |
| `codex/exp-related-work-monitor` | registry, ingestion, tables, thesis note | monitor branch |

## Monitor Command

```bash
uv run python scripts/related_work_monitor.py --render
```

The command scans the worker worktrees for standard FocusParse outputs and
writes:

- `results/hf/related-work-monitor/run_registry.json`
- `results/hf/related-work-monitor/dataset_manifest.json`
- `results/hf/related-work-monitor/protocol_matrix.json`
- `results/hf/related-work-monitor/headline_table.{json,md,csv,html,jsonl}`
- `results/hf/related-work-monitor/related_work_thesis_note.md`

Generated decision-grade commands use the dedicated staging directory
`~/.cache/focusparse/hf_staging_related_work_full` so smoke runs with
`--limit` cannot poison the full-run denominator by leaving
`benchmark.jsonl` at a smaller row count.

## Decision Gates

- All decision-grade rows must use HF revision
  `3774c67f8b814392b6d04c939e904f749a3f52eb`.
- The canonical denominator remains the post-filter `n=148` FocusParse
  subset; raw Hugging Face split counts are not the denominator.
- The FocusParse 66.9% row must be reproduced or linked to recovered raw
  artifacts before it is used as the final thesis row.
- The main ReAct comparator is LlamaIndex ReAct. The older custom ReAct loop is
  appendix-only because its bad result is not a strong industry-standard
  comparison.

## Implementation Snapshot

As of the first monitor pass, each worker branch has an isolated implementation
or reproducibility wrapper:

| Branch | Implementation status | Focused verification |
| --- | --- | --- |
| `codex/exp-basic-vlm-protocols` | protocol manifest/dry-run wrapper | `50 passed` across protocol wrapper + HF CLI tests |
| `codex/exp-llamaindex-react` | official LlamaIndex ReAct comparator | LlamaIndex adapter tests passed; post-smoke patch sets 10 iterations + `early_stopping_method="generate"` |
| `codex/exp-coding-agent` | coding-agent comparator | coding-agent + ReAct tests passed |
| `codex/exp-doclens-baseline` | DocLens-style faithful proxy | DocLens tests and HF CLI tests passed |
| `codex/exp-agenticocr-baseline` | AgenticOCR-style faithful-lite proxy | AgenticOCR + HF CLI tests passed |
| `codex/exp-related-work-monitor` | monitor/rollup tooling | monitor tests passed |

## Smoke Snapshot

One-example live smokes were run with the pinned HF revision and the main
checkout's `.env`; the loader confirmed `148` canonical rows before applying
`--limit 1`. These are wiring checks only, not decision-grade results.

| Row | Smoke status | n | Accuracy |
| --- | --- | --- | --- |
| Basic VLM | completed | 1 | 0/1 |
| LlamaIndex ReAct +2 | completed after iteration-cap fix | 1 | 0/1 |
| LlamaIndex ReAct +4 | completed after iteration-cap fix | 1 | 0/1 |
| Coding Agent +4 | completed | 1 | 0/1 |
| DocLens-style | completed | 1 | 0/1 |
| AgenticOCR-style | completed | 1 | 1/1 |
| FocusParse +4 | completed | 1 | 0/1 |

The initial LlamaIndex ReAct +2 smoke surfaced a real failure mode: official
LlamaIndex hit the max-iteration cap and raised before producing a final
answer. The ReAct branch was patched to use `10` max iterations and
LlamaIndex's `early_stopping_method="generate"`, then both +2 and +4 smokes
completed and wrote standard artifacts. This keeps the main ReAct row a
credible comparator rather than another weak prompt-loop artifact.
